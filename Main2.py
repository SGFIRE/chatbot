import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
import gradio as gr
import requests
from contextlib import contextmanager
from datetime import datetime
import uuid
import logging
import speech_recognition as sr
from moviepy import VideoFileClip

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize Flask app and SQLAlchemy
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///conversations.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Set Gemini API key
gemini_api_key = "YOUR_API_KEY"  # Replace with your actual API key
gemini_api_url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

# Database models
class Character(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text, nullable=False)
    prompt_template = db.Column(db.Text, nullable=False)

class Conversation(db.Model):
    __tablename__ = 'conversation'
    
    id = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(db.Integer, db.ForeignKey('character.id'), nullable=False)
    user_input = db.Column(db.Text, nullable=True)
    bot_response = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    chat_id = db.Column(db.String(36), nullable=True)
    user_id = db.Column(db.Integer, nullable=False)

@contextmanager
def app_context():
    with app.app_context():
        yield

def add_predefined_characters():
    with app_context():
        characters = [
            {
                "name": "Chuck the Clown",
                "description": "A funny clown who tells jokes and entertains.",
                "prompt_template": "You are Chuck the Clown, always ready with a joke and entertainment. Be upbeat, silly, and include jokes in your responses."
            },
            {
                "name": "Sarcastic Pirate",
                "description": "A pirate with a sharp tongue and a love for treasure.",
                "prompt_template": "You are a Sarcastic Pirate, ready to share your tales of adventure. Use pirate slang, be witty, sarcastic, and mention your love for treasure and the sea."
            },
            {
                "name": "Professor Sage",
                "description": "A wise professor knowledgeable about many subjects.",
                "prompt_template": "You are Professor Sage, sharing wisdom and knowledge. Be scholarly, thoughtful, and provide educational information in your responses."
            }
        ]

        for char_data in characters:
            if not Character.query.filter_by(name=char_data["name"]).first():
                new_character = Character(
                    name=char_data["name"],
                    description=char_data["description"],
                    prompt_template=char_data["prompt_template"]
                )
                db.session.add(new_character)
                logger.info(f"Adding predefined character: {char_data['name']}")
        
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error adding predefined characters: {e}")

def add_character(name, description, prompt_template):
    with app_context():
        try:
            if Character.query.filter_by(name=name).first():
                return f"Character '{name}' already exists!"

            new_character = Character(
                name=name,
                description=description,
                prompt_template=prompt_template
            )
            db.session.add(new_character)
            db.session.commit()
            logger.info(f"Successfully added character: {name}")
            return f"Character '{name}' added successfully!\nDescription: {description}"
        
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error adding character: {e}")
            return f"An error occurred while adding the character: {str(e)}"

def get_existing_characters():
    with app_context():
        try:
            characters = Character.query.all()
            return [(char.name, char.description) for char in characters]
        except Exception as e:
            logger.error(f"Error retrieving characters: {e}")
            return [("Error retrieving characters", str(e))]

def chat_with_character(character_name, user_input, user_id, chat_id=None):
    with app_context():
        try:
            character = Character.query.filter_by(name=character_name).first()
            
            if not character:
                return "Character not found.", None
            
            if not chat_id:
                chat_id = str(uuid.uuid4())
            
            # Retrieve previous conversations for context
            previous_conversations = Conversation.query.filter_by(user_id=user_id).order_by(Conversation.timestamp).all()
            context_prompt = " ".join([f"User: {conv.user_input}\nBot: {conv.bot_response}" for conv in previous_conversations])
            prompt_template = character.prompt_template
            full_prompt = f"{prompt_template}\n{context_prompt}\nUser: {user_input}\nBot:"

            payload = {
                "contents": [{
                    "parts": [{"text": full_prompt}]
                }]
            }

            headers = {
                'Content-Type': 'application/json'
            }

            response = requests.post(
                gemini_api_url,
                headers=headers,
                json=payload,
                params={'key': gemini_api_key}
            )

            if response.status_code == 200:
                response_data = response.json()
                if 'candidates' in response_data and len(response_data['candidates']) > 0:
                    bot_response = response_data['candidates'][0]['content']['parts'][0]['text']
                    
                    conversation = Conversation(
                        character_id=character.id,
                        user_input=user_input,
                        bot_response=bot_response,
                        chat_id=chat_id,
                        user_id=user_id
                    )
                    db.session.add(conversation)
                    db.session.commit()
                    logger.info(f"Saved conversation with chat_id: {chat_id}")
                    return bot_response, chat_id
                else:
                    return "An error occurred while generating content: Unexpected response format.", chat_id
            else:
                logger.error(f"Error from Gemini API: {response.json()}")
                return f"An error occurred while generating content: {response.status_code} - {response.text}", chat_id

        except Exception as e:
            logger.error(f"Unexpected error in chat_with_character: {e}")
            return f"An unexpected error occurred: {str(e)}", chat_id

def speech_to_text(audio_file):
    """Convert audio file to text using SpeechRecognition."""
    recognizer = sr.Recognizer()
    with sr.AudioFile(audio_file) as source:
        audio_data = recognizer.record(source)
        try:
            return recognizer.recognize_google(audio_data)
        except sr.UnknownValueError:
            logger.error("Could not understand audio")
            return None
        except sr.RequestError as e:
            logger.error(f"Could not request results from Google Speech Recognition service; {e}")
            return None

def extract_audio_from_video(video_file):
    """Extract audio from video and return the audio file path."""
    audio_file_path = "temp_audio.wav"  # Temporary file name
    try:
        with VideoFileClip(video_file) as video:
            video.audio.write_audiofile(audio_file_path)
    except Exception as e:
        logger.error(f"Error extracting audio from video: {e}")
        return None  # Return None if there's an error
    return audio_file_path

def get_chat_history(user_id):
    """Retrieve chat history for a specific user ID."""
    with app_context():
        conversations = Conversation.query.filter_by(user_id=user_id).order_by(Conversation.timestamp).all()
        return conversations if conversations else []  # Return empty list if no conversations

def create_interface():
    with app.app_context():
        add_predefined_characters()  # Add predefined characters if needed
    
    with gr.Blocks(title="Character Chat System", theme=gr.themes.Default()) as iface:
        current_chat_id = gr.State(value=None)  # State to track the current chat ID
        user_id = gr.State(value=None)  # State to track user ID
        chat_messages = gr.State(value=[])  # State to store chat messages
        
        gr.Markdown(
            "# 🎭 Character Chat System 🎭",
            elem_id="title"
        )
        
        with gr.Tab("Sign In"):
            user_id_input = gr.Textbox(label="User ID", placeholder="Enter your User ID", elem_id="user_id_input", interactive=True, lines=2)
            sign_in_btn = gr.Button("Sign In", variant="primary")
            sign_in_response = gr.Textbox(label="Sign In Response", interactive=False)

            def sign_in(user_id_input):
                user_id.value = user_id_input
                return f"Welcome, {user_id_input}!", user_id_input
            
            sign_in_btn.click(
                fn=sign_in,
                inputs=[user_id_input],
                outputs=[sign_in_response]
            )

        with gr.Tab("Admin: Add Character"):
            with gr.Row():
                with gr.Column():
                    name_input = gr.Textbox(label="Character Name", placeholder="Enter character name", elem_id="name_input")
                    description_input = gr.Textbox(label="Character Description", placeholder="Enter character description", elem_id="description_input")
                    prompt_input = gr.Textbox(label="Prompt Template", placeholder="Enter character prompt template", elem_id="prompt_input", lines=3)
                    add_character_btn = gr.Button("Add Character", elem_id="add_character_btn", variant="primary")
                    add_character_response = gr.Textbox(label="Response", interactive=False, elem_id="response_output")

                    add_character_btn.click(
                        fn=add_character,
                        inputs=[name_input, description_input, prompt_input],
                        outputs=[add_character_response]
                    )
                    
                with gr.Column():
                    gr.Markdown("## 🌟 Existing Characters 🌟", elem_id="existing_chars_title")
                    existing_characters = get_existing_characters()
                    
                    character_list = gr.Dataframe(
                        value=existing_characters,
                        headers=["Name", "Description"],
                        interactive=False,
                        elem_id="character_list"
                    )
                    
                    refresh_characters_btn = gr.Button("Refresh Character List")
                    
                    def refresh_characters():
                        return gr.update(value=get_existing_characters())
                    
                    refresh_characters_btn.click(
                        fn=refresh_characters,
                        outputs=[character_list]
                    )
        
        with gr.Tab("Chat with Character"):
            with gr.Row():
                character_dropdown = gr.Dropdown(
                    label="Choose Character", 
                    choices=[char[0] for char in get_existing_characters()],
                    elem_id="character_dropdown"
                )
                
                chat_id_display = gr.Textbox(
                    label="Current Chat ID", 
                    interactive=False,
                    elem_id="chat_id_display"
                )
                
                user_input = gr.Textbox(
                    label="Your Message",
                    placeholder="Type your message or use audio input",
                    elem_id="user_input",
                    lines=2  # Reduced height for better fitting
                )

                audio_input = gr.Audio(
                    label="Audio Input",
                    type="filepath",  # Type to receive audio file
                    elem_id="audio_input"
                )

                video_input = gr.Video(
                    label="Video Input",  # No type argument needed
                    elem_id="video_input"
                )
                
                chat_btn = gr.Button("Send", variant="primary")
                chat_response = gr.Chatbot(
                    label="Chat Responses", 
                    elem_id="chat_response",
                    height=300  # Set fixed height for the chat display
                )
                
                def handle_chat(character_name, user_input, audio_file, video_file, user_id, chat_messages):
                    if audio_file:
                        user_input = speech_to_text(audio_file)
                        if user_input is None:
                            return chat_messages, None
                    
                    if video_file:
                        audio_file_path = extract_audio_from_video(video_file)
                        if audio_file_path is None:  # Check if audio extraction failed
                            chat_messages.append(("Bot", "Failed to extract audio from video. Please try a different file."))
                            return chat_messages, None

                        extracted_text = speech_to_text(audio_file_path)
                        if extracted_text:
                            user_input += f" {extracted_text}"  # Append transcribed text

                        chat_messages.append(("User", "Video uploaded"))  # Indicate video upload

                    response, new_chat_id = chat_with_character(character_name, user_input, user_id)
                    chat_messages.append(("User", user_input))  # Add user message
                    chat_messages.append(("Bot", response))  # Add bot response
                    return chat_messages, new_chat_id
                
                chat_btn.click(
                    fn=handle_chat,
                    inputs=[character_dropdown, user_input, audio_input, video_input, user_id, chat_messages],
                    outputs=[chat_response, current_chat_id]
                )
        
        with gr.Tab("Chat History"):
            with gr.Row():
                gr.Markdown("## 📜 View Chat History 📜")
                view_history_btn = gr.Button("View History", variant="primary")
                chat_history_display = gr.Dataframe(label="Chat History", interactive=False)

                def load_chat_history(user_id):
                    history = get_chat_history(user_id)
                    return [(conv.id, f"User: {conv.user_input}\nBot: {conv.bot_response} at {conv.timestamp}") for conv in history]

                view_history_btn.click(
                    fn=load_chat_history,
                    inputs=[user_id],
                    outputs=[chat_history_display]
                )

        with gr.Tab("API Status"):
            with gr.Row():
                gr.Markdown("## 🔌 API Connection Status 🔌")
                check_api_btn = gr.Button("Check API Status", variant="primary")
                api_status_display = gr.Textbox(label="API Status", interactive=False)

                def check_api_status():
                    try:
                        response = requests.post(
                            gemini_api_url,
                            headers={'Content-Type': 'application/json'},
                            json={"contents": [{"parts": [{"text": "Hello"}]}]},
                            params={'key': gemini_api_key}
                        )
                        if response.status_code == 200:
                            return "✅ API connection successful! Gemini API is operational."
                        else:
                            return f"❌ API connection failed: {response.status_code} - {response.text}"
                    except Exception as e:
                        return f"❌ API error: {str(e)}"

                check_api_btn.click(
                    fn=check_api_status,
                    outputs=[api_status_display]
                )
    
    return iface

if __name__ == "__main__":
    with app.app_context():
        db.create_all()  # Ensure tables are created
        add_predefined_characters()  # Add predefined characters if needed
    
    chat_interface = create_interface()
    logger.info("Starting Gradio interface...")
    chat_interface.launch(share=True)
