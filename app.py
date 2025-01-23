import asyncio
import aiohttp
from aiogram import Bot, Dispatcher, Router, types
from aiogram.types import Message, ContentType
from aiogram.dispatcher.filters import Command
from aiogram.filters.command import CommandStart
from gradio_client import Client, file
import os

# Telegram Bot Token
BOT_TOKEN = "7844051995:AAG0yvKGMjwHCajxDmzN6O47rcjd4SOzJOw"  # Replace with your token
ADMIN_CHAT_ID = 7046488481  # Replace with your admin Telegram ID

# Gradio API Clients
api_clients = [
    "Kaliboy002/face-swapm",
    "Jonny001/Image-Face-Swap",
]

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)
user_data = {}
current_client_index = 0
semaphore = asyncio.Semaphore(5)  # Limit concurrent tasks to avoid overloading APIs

# Helper: Get the current Gradio Client
def get_client():
    global current_client_index
    return Client(api_clients[current_client_index])

# Helper: Switch to the next Gradio Client
def switch_client():
    global current_client_index
    current_client_index = (current_client_index + 1) % len(api_clients)

# Helper: Download file from Telegram
async def download_file(file_id, save_as):
    file_info = await bot.get_file(file_id)
    file_path = file_info.file_path
    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"

    async with aiohttp.ClientSession() as session:
        async with session.get(file_url) as response:
            if response.status == 200:
                with open(save_as, "wb") as f:
                    f.write(await response.read())
            else:
                raise Exception("Failed to download file from Telegram")

# Helper: Upload file to Catbox
async def upload_to_catbox(file_path):
    async with aiohttp.ClientSession() as session:
        with open(file_path, "rb") as f:
            form = aiohttp.FormData()
            form.add_field("reqtype", "fileupload")
            form.add_field("fileToUpload", f, filename=os.path.basename(file_path))

            async with session.post("https://catbox.moe/user/api.php", data=form) as response:
                if response.status == 200:
                    return await response.text()
                else:
                    raise Exception("Failed to upload file to Catbox")

# Command: Start
@router.message(CommandStart())
async def start(message: Message):
    chat_id = message.chat.id
    user_data[chat_id] = {"step": "awaiting_source"}
    await message.answer("Welcome! Send the source image (face to swap).")

# Handle Photo Messages
@router.message(content_types=[ContentType.PHOTO])
async def handle_photo(message: Message):
    chat_id = message.chat.id

    if chat_id not in user_data:
        await message.answer("Please start with /start.")
        return

    step = user_data[chat_id].get("step", None)

    async with semaphore:
        try:
            if step == "awaiting_source":
                file_id = message.photo[-1].file_id
                user_data[chat_id]["source_image"] = f"{chat_id}_source.jpg"
                await download_file(file_id, user_data[chat_id]["source_image"])
                user_data[chat_id]["step"] = "awaiting_target"
                await message.answer("Great! Now send the target image.")

            elif step == "awaiting_target":
                if "source_image" not in user_data[chat_id]:
                    await message.answer("Source image is missing. Please restart with /start.")
                    user_data.pop(chat_id, None)
                    return

                file_id = message.photo[-1].file_id
                user_data[chat_id]["target_image"] = f"{chat_id}_target.jpg"
                await download_file(file_id, user_data[chat_id]["target_image"])
                await message.answer("Processing your request, please wait...")

                attempts = 0
                while attempts < len(api_clients):
                    try:
                        client = get_client()
                        source_file = user_data[chat_id]["source_image"]
                        target_file = user_data[chat_id]["target_image"]

                        # Perform face swap
                        result_path = client.predict(
                            source_file=file(source_file),
                            target_file=file(target_file),
                            doFaceEnhancer=True,
                            api_name="/predict"
                        )

                        # Upload to Catbox
                        swapped_image_url = await upload_to_catbox(result_path)

                        # Send result to user
                        with open(result_path, "rb") as swapped_file:
                            await bot.send_photo(chat_id, swapped_file, caption=f"Face-swapped image: {swapped_image_url}")
                        break

                    except Exception as e:
                        attempts += 1
                        await bot.send_message(ADMIN_CHAT_ID, f"API error: {e}. Switching to next API.")
                        switch_client()

                else:
                    await message.answer("All APIs failed. Please try again later.")

        except Exception as e:
            await bot.send_message(ADMIN_CHAT_ID, f"Unexpected error: {e}")
            user_data.pop(chat_id, None)

        finally:
            # Clean up files
            for key in ["source_image", "target_image"]:
                if key in user_data[chat_id] and os.path.exists(user_data[chat_id][key]):
                    os.remove(user_data[chat_id][key])
            user_data.pop(chat_id, None)

# Main entry point
async def main():
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
