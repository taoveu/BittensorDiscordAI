import os
import json
import re
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

def _safe_parse_json(content: str) -> dict:
    """Attempt to parse JSON, with fallback regex extraction for truncated responses."""
    # Try direct parse first
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    
    # Try to extract the JSON object via regex (handles preamble/postamble text)
    match = re.search(r'\{.*\}', content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    
    # Last resort: try to salvage truncated JSON by closing open structures
    try:
        # Count unclosed braces/brackets
        fixed = content.rstrip()
        open_brackets = fixed.count('[') - fixed.count(']')
        open_braces = fixed.count('{') - fixed.count('}')
        # Close any open string first
        if fixed and fixed[-1] not in ('}', ']', '"', ','):
            fixed += '"'
        fixed += ']' * max(0, open_brackets)
        fixed += '}' * max(0, open_braces)
        return json.loads(fixed)
    except Exception:
        pass
    
    raise ValueError(f"Could not parse JSON from response: {content[:200]}")

def analyze_discord_exchanges(messages_text: str, recent_messages_text: str = None) -> dict:
    """
    Calls OpenRouter to analyze Discord messages text.
    messages_text: full context (up to 150 msgs) for synthesis
    recent_messages_text: last ~30 msgs used exclusively for sentiment score
    Returns a dict with sentiment_score, executive_synthesis, and critical_points.
    """
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("WARNING: OPENROUTER_API_KEY not set. Returning mock data.")
        return {
            "sentiment_score": 0.5,
            "executive_synthesis": "Mock synthesis because OpenRouter API key is missing. Veuillez ajouter la clé dans le fichier .env.",
            "critical_points": ["Mock point 1", "Mock point 2", "Mock point 3"]
        }

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )

    # Use full history if no recent slice provided
    if not recent_messages_text:
        recent_messages_text = messages_text

    prompt = f"""Tu es un analyste expert de la communauté Bittensor. Analyse ces échanges Discord.

## CONTEXTE HISTORIQUE (pour comprendre le projet, NE PAS utiliser pour le score):
{messages_text}

## MESSAGES RÉCENTS (BASE EXCLUSIVE pour le sentiment_score):
{recent_messages_text}

Règles STRICTES :
- Le **sentiment_score** doit refléter UNIQUEMENT l'humeur des messages récents ci-dessus (-1.0 = très bearish/inquiet, 0.0 = neutre/incertain, +1.0 = très bullish/enthousiaste). NE PAS moyenner avec l'historique.
- L'**executive_synthesis** doit être un paragraphe dense expliquant le contexte global, les débats en cours, et l'humeur actuelle de la communauté.
- Les **critical_points** sont les 3 points techniques les plus importants (plusieurs phrases chacun).

Réponds UNIQUEMENT avec un objet JSON valide :
{{"sentiment_score": float, "executive_synthesis": "string", "critical_points": ["point1", "point2", "point3"]}}"""

    try:
        response = client.chat.completions.create(
            model="meta-llama/llama-3.1-8b-instruct",
            messages=[
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            max_tokens=2048,
            extra_body={
                "provider": {
                    "order": ["Chutes"]
                }
            }
        )
        
        content = response.choices[0].message.content
        if not content:
            raise Exception("Empty or blocked response from OpenRouter API")
            
        return _safe_parse_json(content)
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "Quota" in error_msg or "rate limit" in error_msg.lower():
            import time
            print("⚠️ API Quota limit reached (per minute). Waiting 35 seconds and trying again...")
            time.sleep(35)
            try:
                response = client.chat.completions.create(
                    model="meta-llama/llama-3.1-8b-instruct",
                    messages=[
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    max_tokens=2048,
                    extra_body={
                        "provider": {
                            "order": ["Chutes"]
                        }
                    }
                )
                
                content = response.choices[0].message.content
                if not content:
                     raise Exception("Empty or blocked response from OpenRouter API on retry")
                     
                return _safe_parse_json(content)
            except Exception as retry_e:
                print(f"Error during second OpenRouter generation attempt: {retry_e}")
                return {
                    "sentiment_score": 0.0,
                    "executive_synthesis": f"Error (Quota exceeded and retry failed).",
                    "critical_points": ["Error", "Retry Failed", "Wait a minute and refresh file"]
                }
            
        print(f"Error during OpenRouter generation: {e}")
        return {
            "sentiment_score": 0.0,
            "executive_synthesis": f"Error during analysis: {str(e)[:250]}",
            "critical_points": ["Error analysis point 1", "Error analysis point 2", "Error point 3"]
        }
