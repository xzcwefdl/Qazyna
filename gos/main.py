import requests
import json

MISTRAL_API_KEY = "w62AInWUBvWVOFC0HsdUEyOeeLtyh9dq"

def analyze_tender_with_mistral(tender_text, delivery_days):
    url = "https://api.mistral.ai/v1/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {MISTRAL_API_KEY}"
    }

    # Жесткий системный промпт - это 80% успеха твоего стартапа
    system_prompt = """
    Ты - профессиональный аудитор государственных закупок Республики Казахстан.
    Твоя задача - проанализировать техническую спецификацию и выявить нарушения закона о госзакупках:
    1. Указание конкретных товарных знаков, брендов, моделей (разрешено только "или эквивалент").
    2. Избыточные требования к квалификации поставщика, ограничивающие конкуренцию.
    3. Неадекватные сроки (например, поставка сложного оборудования за 2-3 дня).

    Ответь строго в формате JSON:
    {
      "risk_score": 0-100,
      "violations_found": ["список нарушений или пустой массив"],
      "explanation": "краткое объяснение коррупционного риска"
    }
    """

    user_message = f"Срок поставки: {delivery_days} дней.\nТекст спецификации:\n{tender_text[:15000]}" # Ограничиваем текст, чтобы не выйти за лимит токенов

    data = {
        "model": "mistral-large-latest", # или mistral-small-latest для экономии
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        "response_format": {"type": "json_object"} # Заставляем модель выдавать строгий JSON
    }

    response = requests.post(url, headers=headers, json=data)

    if response.status_code == 200:
        return json.loads(response.json()['choices'][0]['message']['content'])
    else:
        print(f"Ошибка Mistral API: {response.text}")
        return None
