import json
import sys
import os

input_path = r"C:\Users\G00dS0ul🤡\.gemini\antigravity\brain\87727518-e3e1-4d64-8a68-06b0a37035f1\.system_generated\logs\transcript_full.jsonl"
output_path = "sanitized_transcript.json"
search_str = r"C:\Users\G00dS0ul🤡"

messages = []

def scrub(text):
    if not isinstance(text, str):
        return text
    # Replace backslashes in search with forward slashes too just in case
    text = text.replace(search_str, "~")
    text = text.replace(search_str.replace('\\', '/'), "~")
    return text

with open(input_path, 'r', encoding='utf-8') as f:
    for line in f:
        if not line.strip(): continue
        step = json.loads(line)
        
        # Determine role
        role = None
        if step.get("source") in ["USER_EXPLICIT", "USER_IMPLICIT", "SYSTEM"]:
            # Actually devrelay just expects user or assistant
            # Combine system messages into user
            role = "user"
        elif step.get("source") == "MODEL":
            role = "assistant"
        else:
            role = "assistant" # fallback
            
        content_blocks = []
        
        # Text content
        if "content" in step and step["content"]:
            content_blocks.append({
                "type": "text",
                "text": scrub(step["content"])
            })
            
        # Tool calls
        if "tool_calls" in step and step["tool_calls"]:
            for tc in step["tool_calls"]:
                # Devrelay expects: "type": "tool_call", "name": "...", "input": "...", "output": "..."
                # In Antigravity: tc is dict maybe?
                # Actually, in Antigravity transcript, it's not clear. 
                # Let's just stringify whatever it is.
                name = tc.get("name") if isinstance(tc, dict) else str(tc)
                input_str = json.dumps(tc.get("arguments", {})) if isinstance(tc, dict) else ""
                
                # We don't have output here directly since it's an async system, but we'll try to map it
                content_blocks.append({
                    "type": "tool_call",
                    "name": scrub(name),
                    "input": scrub(input_str),
                    "output": "..." # Output is not easily mapped, DevRelay doesn't strictly validate output
                })
        
        if content_blocks:
            messages.append({
                "role": role,
                "content": content_blocks
            })

# Ensure last model message has a fallback if needed, but DevRelay might not validate pair strictly.
curated = {
    "messages": messages,
    "metadata": {
        "tool_name": "gemini_cli",
        "session_id": "87727518-e3e1-4d64-8a68-06b0a37035f1",
        "total_messages": len(messages)
    }
}

with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(curated, f, indent=2)

print("Saved to", output_path)
