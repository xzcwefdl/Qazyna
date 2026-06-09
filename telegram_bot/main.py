import logging
import telebot
import requests
import os

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Токен вашего бота
TOKEN = "6976164022:AAGHgvYsiEPPdH9q8rloO5stCZa2LmaxlRs"

# Ключ API Mistral AI
MISTRAL_API_KEY = "w62AInWUBvWVOFC0HsdUEyOeeLtyh9dq"

# Инициализация бота
bot = telebot.TeleBot(TOKEN)

# Текущая выбранная модель
current_model = "mistral-tiny"

# Список доступных моделей
AVAILABLE_MODELS = [
    "mistral-tiny",
    "mistral-small",
    "mistral-medium",
    "mistral-large"
]

# Обработчик команды /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user = message.from_user
    welcome_message = (
        f"Hi {user.first_name}!\n"
        f"I am your AI assistant. Send me a message and I will try to help you.\n\n"
        f"Current model: {current_model}\n"
        f"Available models: {', '.join(AVAILABLE_MODELS)}"
    )
    bot.reply_to(message, welcome_message)

# Обработчик команды /model
@bot.message_handler(commands=['model'])
def set_model(message):
    global current_model
    try:
        # Получаем аргументы команды
        args = message.text.split()[1:]
        if not args:
            bot.reply_to(message, f"Please specify a model. Available models: {', '.join(AVAILABLE_MODELS)}")
            return

        requested_model = args[0]
        if requested_model in AVAILABLE_MODELS:
            current_model = requested_model
            bot.reply_to(message, f"Model set to: {current_model}")
        else:
            bot.reply_to(message, f"Unknown model: {requested_model}. Available models: {', '.join(AVAILABLE_MODELS)}")
    except Exception as e:
        logger.error(f"Error in set_model: {e}")
        bot.reply_to(message, "An error occurred while setting the model.")

# Функция для взаимодействия с Mistral AI
def call_mistral_api(prompt: str, model: str) -> str:
    url = "https://api.mistral.ai/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {MISTRAL_API_KEY}"
    }
    data = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}]
    }

    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content']
    except Exception as e:
        logger.error(f"Error calling Mistral API: {e}")
        return f"Sorry, I couldn't process your request. Error: {str(e)}"

# Обработчик текстовых сообщений
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_message = message.text
    logger.info(f"User message: {user_message}")

    # Формируем ответ с использованием Mistral AI
    response = call_mistral_api(user_message, current_model)

    bot.reply_to(message, response)

if __name__ == '__main__':
    logger.info("Starting bot...")
    bot.infinity_polling()
