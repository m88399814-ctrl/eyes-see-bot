from transformers import AutoTokenizer, AutoModelForCausalLM
import torch

model_name = "google/gemma-2b-it"

print("Загружаю модель, подожди...")

tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForCausalLM.from_pretrained(
    model_name,
    device_map="auto",
    torch_dtype=torch.float32
)

print("Модель загружена!")

while True:
    question = input("\nТы: ")
    if question.lower() == "exit":
        break

    inputs = tokenizer(question, return_tensors="pt").to(model.device)
    output = model.generate(
        **inputs,
        max_new_tokens=200,
        temperature=0.7,
        pad_token_id=tokenizer.eos_token_id
    )
    answer = tokenizer.decode(output[0], skip_special_tokens=True)
    print("\nGemma:", answer)