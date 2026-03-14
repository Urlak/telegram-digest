import logging
from google import genai
from src.config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

def summarize_messages(grouped_messages: dict) -> list[str]:
    """
    Summarizes messages using Gemini AI.
    Groups are summarized independently so contexts never mix.
    Returns a list of Markdown formatted summary strings.
    """
    if not grouped_messages:
        return []

    # Initialize the new genai client
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    summaries = []
    
    for group_name, messages in grouped_messages.items():
        logger.info(f"Summarizing {len(messages)} messages for group: {group_name}")
        
        prompt = f"Summarize the following recent Telegram messages from the group '{group_name}'.\n"
        prompt += "IMPORTANT: Write the summary in the exact same language as the original messages (mostly Russian).\n"
        prompt += "Keep the summary brief, information-dense, and output as clear Markdown bullet points.\n\n"
        
        # Attach the messages with their contextual metadata
        for msg in reversed(messages):  # Reversing them means chronological order generally
            # Shorten timestamp to [HH:MM] to save tokens
            short_time = msg['date'][-5:] 
            prompt += f"[{short_time}] {msg['sender_name']}: {msg['text']}\n"
            
        try:
            # Call Gemini using the new syntax and `gemini-2.5-flash`
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
            )
            # Add a clear Markdown header pointing out which group this is for
            group_summary = f"### Summary for {group_name}\n\n{response.text.strip()}\n"
            summaries.append(group_summary)
        except Exception as e:
            logger.error(f"Error calling Gemini API for group {group_name}: {e}")
            summaries.append(f"### Summary for {group_name}\n\n*Error summarizing messages: {e}*\n")
            
    return summaries
