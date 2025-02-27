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
gemini_api_key = 
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
    user_id = db.Column(db.Integer, nullable=False)  # Added user_id

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
            
            # Include the character's prompt template in the payload
            prompt_template = character.prompt_template
            full_prompt = f"{prompt_template}\nUser: {user_input}\nBot:"

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

            # Check if the response was successful
            if response.status_code == 200:
                response_data = response.json()
                # Ensure 'candidates' and the expected structure exist
                if 'candidates' in response_data and len(response_data['candidates']) > 0:
                    bot_response = response_data['candidates'][0]['content']['parts'][0]['text']
                    
                    conversation = Conversation(
                        character_id=character.id,
                        user_input=user_input,
                        bot_response=bot_response,
                        chat_id=chat_id,
                        user_id=user_id  # Include user_id here
                    )
                    db.session.add(conversation)
                    db.session.commit()
                    logger.info(f"Saved conversation with chat_id: {chat_id}")
                    return bot_response, chat_id
                else:
                    logger.error(f"Unexpected response structure: {response_data}")
                    return "An error occurred while generating content: Unexpected response format.", chat_id
            else:
                logger.error(f"Error from Gemini API: {response.json()}")
                return f"An error occurred while generating content: {response.status_code} - {response.text}", chat_id

        except Exception as e:
            logger.error(f"Unexpected error in chat_with_character: {e}")
            return f"An unexpected error occurred: {str(e)}", chat_id

def get_chat_history(chat_id):
    with app_context():
        try:
            if not chat_id:
                return "No chat ID provided."
            
            conversations = Conversation.query.filter_by(chat_id=chat_id).order_by(Conversation.timestamp).all()
            
            if not conversations:
                return "No chat history found for this ID."
            
            character = Character.query.get(conversations[0].character_id)
            character_name = character.name if character else "Unknown Character"
            
            history = f"Chat History with {character_name} (ID: {chat_id}):\n\n"
            
            for conv in conversations:
                timestamp = conv.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                history += f"[{timestamp}]\n"
                history += f"User: {conv.user_input}\n"
                history += f"Bot: {conv.bot_response}\n\n"
            
            return history
            
        except Exception as e:
            logger.error(f"Error retrieving chat history: {e}")
            return f"Error retrieving chat history: {str(e)}"

def get_all_chat_ids():
    with app_context():
        try:
            query = db.session.query(
                Conversation.chat_id,
                Character.name.label('character_name'),
                db.func.min(Conversation.timestamp).label('start_time'),
                db.func.count(Conversation.id).label('message_count')
            ).join(
                Character, Conversation.character_id == Character.id
            ).filter(
                Conversation.chat_id.isnot(None)
            ).group_by(
                Conversation.chat_id, Character.name
            ).order_by(
                db.func.min(Conversation.timestamp).desc()
            ).all()
            
            chat_list = []
            for chat in query:
                start_time = chat.start_time.strftime("%Y-%m-%d %H:%M:%S")
                chat_list.append([
                    chat.chat_id, 
                    chat.character_name, 
                    start_time, 
                    chat.message_count
                ])
            
            return chat_list
            
        except Exception as e:
            logger.error(f"Error retrieving chat IDs: {e}")
            return [["Error", "Error retrieving chats", str(e), ""]]

def update_database_schema():
    with app.app_context():
        try:
            inspector = db.inspect(db.engine)
            if not inspector.has_table('conversation'):
                logger.info("Creating conversation table...")
                db.create_all()
                return
                
            columns = [col['name'] for col in inspector.get_columns('conversation')]
            
            with db.engine.connect() as connection:
                transaction = connection.begin()
                try:
                    if 'user_input' not in columns:
                        logger.info("Adding missing 'user_input' column to conversation table...")
                        connection.execute(text('ALTER TABLE conversation ADD COLUMN user_input TEXT'))
                    
                    if 'chat_id' not in columns:
                        logger.info("Adding missing 'chat_id' column to conversation table...")
                        connection.execute(text('ALTER TABLE conversation ADD COLUMN chat_id VARCHAR(36)'))
                    
                    if 'bot_response' not in columns:
                        logger.info("Adding missing 'bot_response' column to conversation table...")
                        connection.execute(text('ALTER TABLE conversation ADD COLUMN bot_response TEXT NOT NULL DEFAULT ""'))
                    
                    if 'timestamp' not in columns:
                        logger.info("Adding missing 'timestamp' column to conversation table...")
                        connection.execute(text('ALTER TABLE conversation ADD COLUMN timestamp DATETIME DEFAULT CURRENT_TIMESTAMP'))
                    
                    if 'user_id' not in columns:  # Check for user_id
                        logger.info("Adding missing 'user_id' column to conversation table...")
                        connection.execute(text('ALTER TABLE conversation ADD COLUMN user_id INTEGER NOT NULL'))  # Add user_id
                    
                    transaction.commit()
                    logger.info("Database schema is now up to date!")
                except Exception as e:
                    transaction.rollback()
                    logger.error(f"Error in transaction: {e}")
                    raise
                    
        except Exception as e:
            logger.error(f"Error updating database schema: {e}")

def create_interface():
    with app.app_context():
        db.create_all()  # Ensure tables are created
        update_database_schema()  # Update schema if needed
        add_predefined_characters()  # Add predefined characters
    
    with gr.Blocks(title="Character Chat System", theme=gr.themes.Default()) as iface:
        current_chat_id = gr.State(value=None)  # State to track the current chat ID
        
        gr.Markdown(
            "# 🎭 Character Chat System 🎭",
            elem_id="title"
        )
        
        with gr.Tab("Admin: Add Character"):
            with gr.Row():
                with gr.Column():
                    name_input = gr.Textbox(label="Character Name", placeholder="Enter character name", elem_id="name_input")
                    description_input = gr.Textbox(label="Character Description", placeholder="Enter character description", elem_id="description_input")
                    prompt_input = gr.Textbox(label="Prompt Template", placeholder="Enter character prompt template", elem_id="prompt_input")
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
                with gr.Column():
                    character_dropdown = gr.Dropdown(
                        label="Choose Character", 
                        choices=[char[0] for char in existing_characters],
                        elem_id="character_dropdown"
                    )
                    
                    chat_id_display = gr.Textbox(
                        label="Current Chat ID", 
                        interactive=False,
                        elem_id="chat_id_display"
                    )
                    
                    user_id_input = gr.Textbox(
                        label="User ID", 
                        placeholder="Enter your user ID",
                        elem_id="user_id_input"
                    )
                    
                    new_chat_btn = gr.Button("Start New Chat", variant="secondary")
                    
                    user_input = gr.Textbox(
                        label="Your Message", 
                        placeholder="Type your message here...",
                        elem_id="user_input"
                    )
                    
                    chat_btn = gr.Button("Send", variant="primary")
                    chat_response = gr.Textbox(
                        label="Response", 
                        interactive=False,
                        elem_id="chat_response"
                    )
                    
                    def handle_chat(character_name, message, user_id, chat_id):
                        if not character_name:
                            return "Please select a character first.", chat_id, chat_id
                        
                        response, new_chat_id = chat_with_character(character_name, message, user_id, chat_id)
                        return response, new_chat_id, new_chat_id
                    
                    def start_new_chat():
                        new_id = str(uuid.uuid4())
                        return new_id, new_id
                    
                    chat_btn.click(
                        fn=handle_chat,
                        inputs=[character_dropdown, user_input, user_id_input, current_chat_id],
                        outputs=[chat_response, current_chat_id, chat_id_display]
                    )
                    
                    new_chat_btn.click(
                        fn=start_new_chat,
                        outputs=[current_chat_id, chat_id_display]
                    )
        
        with gr.Tab("Chat History"):
            with gr.Row():
                with gr.Column():
                    gr.Markdown("## 📜 View Chat History 📜")
                    
                    refresh_chats_btn = gr.Button("Refresh Chat List", variant="primary")
                    
                    chats_table = gr.Dataframe(
                        headers=["Chat ID", "Character", "Start Time", "Messages"],
                        interactive=True,
                        elem_id="chats_table"
                    )
                    
                    selected_chat_id = gr.Textbox(
                        label="Selected Chat ID", 
                        placeholder="Enter or select a chat ID to view its history",
                        elem_id="selected_chat_id"
                    )
                    
                    view_history_btn = gr.Button("View Chat History", variant="primary")
                    
                    chat_history_display = gr.Textbox(
                        label="Chat History", 
                        interactive=False,
                        elem_id="chat_history_display",
                        lines=20
                    )
                    
                    def refresh_chats():
                        return gr.update(value=get_all_chat_ids())
                    
                    def view_selected_chat(chat_id):
                        return get_chat_history(chat_id)
                    
                    def set_selected_chat(evt: gr.SelectData):
                        return evt.data[0][0]
                    
                    refresh_chats_btn.click(
                        fn=refresh_chats,
                        outputs=[chats_table]
                    )
                    
                    chats_table.select(
                        fn=set_selected_chat,
                        outputs=[selected_chat_id]
                    )
                    
                    view_history_btn.click(
                        fn=view_selected_chat,
                        inputs=[selected_chat_id],
                        outputs=[chat_history_display]
                    )
                    
        with gr.Tab("API Status"):
            with gr.Row():
                with gr.Column():
                    gr.Markdown("## 🔌 API Connection Status 🔌")
                    
                    check_api_btn = gr.Button("Check API Status", variant="primary")
                    
                    api_status_display = gr.Textbox(
                        label="API Status", 
                        interactive=False,
                        elem_id="api_status_display"
                    )
                    
                    def check_api_status():
                        # Implement a simple test call to the Gemini API (if applicable)
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
        try:
            db.create_all()
            update_database_schema()
            add_predefined_characters()
            logger.info("Database setup completed successfully")
        except Exception as e:
            logger.error(f"Error during database setup: {e}")

    chat_interface = create_interface()
    logger.info("Starting Gradio interface...")
    chat_interface.launch(share=True)
