def extract_final_answer(content: str) -> str:
    """Extract the final answer from the model's known thinking format."""
    if "</think>" in content:
        content = content.rsplit("</think>", 1)[1]

    return content.strip()