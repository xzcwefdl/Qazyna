import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, GenerationConfig

model_id = "Zyphra/ZAYA1-8B"

print("Загрузка токенизатора из форка Zyphra...")
tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)

print("Загрузка оригинальных весов модели в bfloat16...")
model = AutoModelForCausalLM.from_pretrained(
    model_id,
    torch_dtype=torch.bfloat16,
    device_map="auto",
    trust_remote_code=True
)

# ХАК: Вычищаем кривой top_k прямо из встроенного конфига модели
if hasattr(model, "generation_config"):
    model.generation_config.top_k = None  # Или 0, убираем дефолт от Zyphra

# Создаем чистый пользовательский конфиг
generation_config = GenerationConfig(
    temperature=0.6,
    top_p=0.95,
    do_sample=True,
    max_new_tokens=1024,
    pad_token_id=tokenizer.pad_token_id if tokenizer.pad_token_id is not None else tokenizer.eos_token_id,
    eos_token_id=tokenizer.eos_token_id
)

# На всякий случай явно убираем top_k и отсюда
generation_config.top_k = None

prompt = "Напиши функцию на Python для быстрого поиска подстроки в строке (алгоритм Кнута-Морриса-Пратта) и объясни шаги."

messages = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": prompt}
]

inputs = tokenizer.apply_chat_template(messages, return_tensors="pt").to("cuda")

print("Генерация ответа (из-за offload на CPU первый токен может создаваться несколько минут)...")
with torch.no_grad():
    outputs = model.generate(
        inputs,
        generation_config=generation_config,
        top_k=0  # Принудительный хардкод прямо в аргументы метода, чтобы перебить любые слияния
    )

response = tokenizer.decode(outputs[0][inputs.shape[1]:], skip_special_tokens=True)
print("\n[Ответ ZAYA1-8B]:")
print(response)
