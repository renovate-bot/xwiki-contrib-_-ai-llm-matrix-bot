import asyncio
import datetime
import json
import logging
import os
import markdown2
from typing import Dict, List, Optional, Any

import jwt
import requests
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from nio import (
    AsyncClient, AsyncClientConfig, MatrixRoom, RoomMessageText,
    LoginResponse, EncryptionError, KeyVerificationStart, KeyVerificationCancel,
    KeyVerificationKey, KeyVerificationMac, ToDeviceError, ToDeviceResponse,
    InviteMemberEvent
)
from nio.store import SqliteStore
from openai import OpenAI

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Config:
    def __init__(self, config_file: str):
        with open(config_file, 'r') as f:
            config = json.load(f)
        
        self.models = config[0].get('models', [])
        self.restrict_to_specified_models = config[0].get('restrict_to_specified_models', False)
        self.server = config[1]['server']
        self.xwiki_endpoint = config[1]['xwiki_xwiki_v1_endpoint']
        self.matrix_username = config[1]['matrix_username']
        self.matrix_password = config[1]['matrix_password']
        self.device_id = config[1]['device_id']
        self.channels = config[1]['channels']
        self.personality = config[1]['personality']
        self.admins = config[1]['admins']
        self.forbidden_words = config[1].get('forbidden_words', [])
        self.default_model = config[1].get('default_model', 'AI.Models.waise-llama3')
        self.jwt_payload = config[1].get('jwt_payload', {})
        self.moderation_enabled = config[1].get('moderation_enabled', True)
        self.moderation_strategy = config[1].get('moderation_strategy', 'forbidden_words')
        self.sync_timeout = config[1].get('sync_timeout', 30000)
        self.response_temperature = config[1].get('response_temperature', 1)
        self.jwt_expiration_hours = config[1].get('jwt_expiration_hours', 3)
        self.auto_join_rooms = config[1].get('auto_join_rooms', True)
class InfiniGPT:
    def __init__(self):
        self.config = Config("config.json")
        self.private_key = self._load_private_key()
        self.client = self._setup_matrix_client()
        self.openai = None
        self.models = []
        self.default_model = self.config.default_model
        self.current_model = None
        self.join_time = datetime.datetime.now(datetime.timezone.utc)
        self.messages: Dict[str, Dict[str, List[Dict[str, str]]]] = {}
        self.prompt = (
            "assume the personality of ",
            ".  roleplay and never break character. keep your responses relatively short."
        )
        self.room_models = {}

    def _load_private_key(self):
        with open("private.pem", "rb") as key_file:
            return serialization.load_pem_private_key(
                key_file.read(),
                password=None,
                backend=default_backend()
            )

    def _setup_matrix_client(self):
        store_path = "nio_store/"
        os.makedirs(store_path, exist_ok=True)
        client_config = AsyncClientConfig(
            store_sync_tokens=True,
            encryption_enabled=True,
        )
        return AsyncClient(
            self.config.server,
            self.config.matrix_username,
            device_id=self.config.device_id,
            store_path=store_path,
            config=client_config
        )

    def _generate_jwt(self, username: str) -> str:
        current_time = datetime.datetime.now(datetime.timezone.utc)
        payload = self.config.jwt_payload.copy()
        payload.update({
            "sub": username,
            "exp": current_time + datetime.timedelta(hours=self.config.jwt_expiration_hours),
            "iat": current_time,
            "nbf": current_time,
        })
        return jwt.encode(payload, self.private_key, algorithm="EdDSA")

    def model_list(self) -> List[str]:
        try:
            jwt_token = self._generate_jwt(self.config.matrix_username)
            headers = {"Authorization": f"Bearer {jwt_token}"}
            response = requests.get(f"{self.config.xwiki_endpoint}/models", headers=headers)
            response.raise_for_status()
            data = response.json()
            available_models = [model['name'] for model in data['data']]
            
            if self.config.restrict_to_specified_models:
                allowed_models = set(self.config.models) & set(available_models)
                models = sorted(allowed_models)
            else:
                models = sorted(available_models)
            
            self.model_mapping = {model['name']: model['id'] for model in data['data'] if model['name'] in models}
            self.models = models
            return models
        except requests.RequestException as e:
            logger.error(f"Error fetching models: {e}")
            return self.config.models if self.config.restrict_to_specified_models else []
        except KeyError as e:
            logger.error(f"Unexpected response format when fetching models: {e}")
            return self.config.models if self.config.restrict_to_specified_models else []

    def initialize_openai(self, api_key: str):
        self.openai = OpenAI(
            api_key=api_key,
            base_url=self.config.xwiki_endpoint
        )
        available_models = self.model_list()
        if available_models:
            if self.default_model not in available_models:
                logger.warning(f"Default model {self.default_model} not available. Using first available model.")
                self.current_model = available_models[0]
            else:
                self.current_model = self.default_model
        else:
            logger.error("No models available. Bot may not function correctly.")
            self.current_model = self.default_model
            
    def change_model(self, room_id: str, model_id: str):
        self.room_models[room_id] = model_id

    async def display_name(self, user: str) -> Optional[str]:
        try:
            name = await self.client.get_displayname(user)
            return name.displayname
        except Exception as e:
            logger.error(f"Error getting display name: {e}")
            return None

    async def send_markdown_message(self, channel: str, message: str):
        try:
            html_content = markdown2.markdown(message)
            await self.client.room_send(
                room_id=channel,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "format": "org.matrix.custom.html",
                    "body": message,
                    "formatted_body": html_content
                },
                ignore_unverified_devices=True,
            )
        except Exception as e:
            logger.error(f"Error sending markdown message: {e}")

    async def send_message(self, channel: str, message: str):
        try:
            await self.client.room_send(
                room_id=channel,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": message},
                ignore_unverified_devices=True,
            )
        except Exception as e:
            logger.error(f"Error sending message: {e}")

    async def moderate(self, message: str) -> bool:
        if not self.config.moderation_enabled:
            return False
        
        if self.config.moderation_strategy == 'forbidden_words':
            return any(word.lower() in message.lower() for word in self.config.forbidden_words)
        else:
            logger.warning(f"Unknown moderation strategy: {self.config.moderation_strategy}")
            return False

    async def add_history(self, role: str, channel: str, sender: str, message: str):
        if channel not in self.messages:
            self.messages[channel] = {}
        
        if sender not in self.messages[channel]:
            self.messages[channel][sender] = [
                {"role": "system", "content": self.prompt[0] + self.config.personality + self.prompt[1]},
                {"role": role, "content": message}
            ]
        else:
            self.messages[channel][sender].append({"role": role, "content": message})

    async def respond(self, channel: str, sender: str, message: List[Dict[str, str]], sender2: Optional[str] = None):
        try:
            model = self.room_models.get(channel, self.default_model)
            if not model:
                logger.error("No model selected for this room. Using default model.")
                model = self.default_model

            response = self.openai.chat.completions.create(
                model=model,
                temperature=self.config.response_temperature,
                messages=message
            )
            response_text = response.choices[0].message.content.strip('"')
            await self.add_history("assistant", channel, sender, response_text)
            
            display_name = await self.display_name(sender2 or sender)
            response_text = f"{display_name}:\n\n{response_text}"
            
            await self.send_markdown_message(channel, response_text)
            
            if len(self.messages[channel][sender]) > 24:
                del self.messages[channel][sender][1:3]
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            await self.send_message(channel, "An error occurred while generating a response. Please try again later.")

    async def persona(self, channel: str, sender: str, persona: str):
        try:
            self.messages[channel][sender].clear()
        except KeyError:
            pass
        personality = self.prompt[0] + persona + self.prompt[1]
        await self.add_history("system", channel, sender, personality)

    async def custom(self, channel: str, sender: str, prompt: str):
        try:
            self.messages[channel][sender].clear()
        except KeyError:
            pass
        await self.add_history("system", channel, sender, prompt)

    async def message_callback(self, room: MatrixRoom, event: RoomMessageText):
        if not isinstance(event, RoomMessageText):
            return

        message_time = datetime.datetime.fromtimestamp(event.server_timestamp / 1000, tz=datetime.timezone.utc)
        message = event.body
        sender = event.sender
        room_id = room.room_id

        if message_time <= self.join_time or sender == self.config.matrix_username:
            return

        try:
            sender_display = await self.display_name(sender)
        except Exception as e:
            logger.error(f"Error getting display name for {sender}: {e}")
            sender_display = sender

        if message.startswith(".ai ") or message.startswith(self.client.user_id):
            await self._handle_ai_command(room_id, sender, sender_display, message)
        elif message.startswith(".x "):
            await self._handle_x_command(room_id, sender, sender_display, message)
        elif message.startswith(".persona "):
            await self._handle_persona_command(room_id, sender, sender_display, message)
        elif message.startswith(".custom "):
            await self._handle_custom_command(room_id, sender, sender_display, message)
        elif message.startswith(".model"):
            await self._handle_model_command(room_id, sender, sender_display, message)
        elif message.startswith(".reset"):
            await self._handle_reset_command(room_id, sender, sender_display)
        elif message.startswith(".stock"):
            await self._handle_stock_command(room_id, sender, sender_display)
        elif message.startswith(".help"):
            await self._handle_help_command(room_id, sender_display)

    async def _handle_ai_command(self, room_id: str, sender: str, sender_display: str, message: str):
        m = message.split(" ", 1)[1]
        flagged = await self.moderate(m)
        if flagged:
            await self.send_message(room_id, f"{sender_display}: This message violates the usage policy and was not sent.")
        else:
            await self.add_history("user", room_id, sender, m)
            await self.respond(room_id, sender, self.messages[room_id][sender])

    async def _handle_x_command(self, room_id: str, sender: str, sender_display: str, message: str):
        m = message.split(" ", 2)
        if len(m) > 2:
            disp_name, m = m[1], m[2]
            name_id = ""
            if room_id in self.messages:
                for user in self.messages[room_id]:
                    try:
                        matrix_username = await self.display_name(user)
                        if disp_name == matrix_username:
                            name_id = user
                    except Exception as e:
                        logger.error(f"Error getting display name for {user}: {e}")
                        name_id = disp_name
                
                flagged = await self.moderate(m)
                if flagged:
                    await self.send_message(room_id, f"{sender_display}: This message violates the usage policy and was not sent.")
                else:
                    await self.add_history("user", room_id, name_id, m)
                    await self.respond(room_id, name_id, self.messages[room_id][name_id], sender)

    async def _handle_persona_command(self, room_id: str, sender: str, sender_display: str, message: str):
        m = message.split(" ", 1)[1]
        flagged = await self.moderate(m)
        if flagged:
            await self.send_message(room_id, f"{sender_display}: This persona violates the usage policy and was not set. Choose a new persona.")
        else:
            await self.persona(room_id, sender, m)
            await self.respond(room_id, sender, self.messages[room_id][sender])

    async def _handle_custom_command(self, room_id: str, sender: str, sender_display: str, message: str):
        m = message.split(" ", 1)[1]
        flagged = await self.moderate(m)
        if flagged:
            await self.send_message(room_id, f"{sender_display}: This custom prompt violates the usage policy and was not set.")
        else:
            await self.custom(room_id, sender, m)
            await self.respond(room_id, sender, self.messages[room_id][sender])

    async def _handle_model_command(self, room_id: str, sender: str, sender_display: str, message: str):
        if message == ".model" or message == ".models":
            current_model = self.room_models.get(room_id, self.default_model)
            await self.send_message(room_id, f"Current model for this room: {current_model}\nAvailable models: " + ", ".join(self.models))
        elif message.startswith(".model ") and sender in self.config.admins:
            model_name = message.split(" ", 1)[1]
            if model_name in self.model_mapping:
                model_id = self.model_mapping[model_name]
                self.change_model(room_id, model_id)
                await self.send_message(room_id, f"Model for this room set to {model_name} ({model_id})")
            elif model_name == "reset":
                self.change_model(room_id, self.default_model)
                await self.send_message(room_id, f"Model for this room reset to {self.default_model}")
            else:
                await self.send_message(room_id, "Invalid model name. Try again.")

    async def _handle_reset_command(self, room_id: str, sender: str, sender_display: str):
            if room_id in self.messages and sender in self.messages[room_id]:
                self.messages[room_id][sender].clear()
                await self.persona(room_id, sender, self.config.personality)
            await self.send_message(room_id, f"{self.client.user_id} reset to default for {sender_display}")

    async def _handle_stock_command(self, room_id: str, sender: str, sender_display: str):
        if room_id in self.messages:
            if sender in self.messages[room_id]:
                self.messages[room_id][sender].clear()
        else:
            self.messages[room_id] = {}
            self.messages[room_id][sender] = []
        await self.send_message(room_id, f"Stock settings applied for {sender_display}")

    async def _handle_help_command(self, room_id: str, sender_display: str):
        try:
            with open("help.txt", "r") as f:
                help_text = f.read()
            await self.send_message(room_id, help_text)
        except Exception as e:
            logger.error(f"Error loading help file: {e}")
            await self.send_message(room_id, f"{sender_display}: An error occurred while loading the help file. Please try again later.")

    async def join_rooms(self):
        for room_id in self.config.channels:
            try:
                await self.client.join(room_id)
                logger.info(f"Joined room {room_id}")
            except Exception as e:
                logger.error(f"Failed to join room {room_id}: {e}")

    async def handle_invite(self, room: MatrixRoom, event: InviteMemberEvent):
        if event.membership != "invite":
            return

        if self.config.auto_join_rooms or room.room_id in self.config.channels:
            try:
                await self.client.join(room.room_id)
                logger.info(f"Joined room {room.room_id} after invitation")
            except Exception as e:
                logger.error(f"Failed to join room {room.room_id} after invitation: {e}")
        else:
            logger.info(f"Ignored invitation to room {room.room_id} as it's not in the configured channels and auto-join is disabled")

    async def periodic_room_check(self):
        while True:
            await asyncio.sleep(300)  # Check every 5 minutes
            await self.join_rooms()

    async def main(self):
        login_response = await self.client.login(self.config.matrix_password)
        if isinstance(login_response, LoginResponse):
            logger.info(f"Logged in as {self.config.matrix_username}, device id: {login_response.device_id}.")
        else:
            logger.error(f"Failed to login: {login_response}")
            return

        await self.client.sync(full_state=True, timeout=30000)

        self.client.user_id = await self.display_name(self.config.matrix_username)

        # Join configured rooms
        await self.join_rooms()

        # Set up callbacks
        self.client.add_event_callback(self.message_callback, RoomMessageText)
        self.client.add_event_callback(self.handle_invite, InviteMemberEvent)

        # Start periodic room check
        asyncio.create_task(self.periodic_room_check())

        # Set up verification callbacks
        self.client.add_to_device_callback(self.verification_start, KeyVerificationStart)
        self.client.add_to_device_callback(self.verification_key, KeyVerificationKey)
        self.client.add_to_device_callback(self.verification_mac, KeyVerificationMac)
        self.client.add_to_device_callback(self.verification_cancel, KeyVerificationCancel)

        await self.client.sync_forever(timeout=self.config.sync_timeout)

    async def verification_start(self, event):
        """Handle verification start event."""
        logger.info(f"Verification started: {event}")
        
        if self.client.key_verifications:
            logger.info("Verification already in progress, ignoring.")
            return

        resp = await self.client.accept_key_verification(event.transaction_id)
        if isinstance(resp, ToDeviceResponse):
            logger.info("Verification accepted!")
        elif isinstance(resp, ToDeviceError):
            logger.error(f"Failed to accept verification: {resp}")

    async def verification_key(self, event):
        """Handle verification key event."""
        logger.info(f"Verification key received: {event}")
        sas = self.client.get_active_sas(event.sender, event.from_device)
        if sas:
            resp = await self.client.confirm_short_auth_string(event.transaction_id)
            if isinstance(resp, ToDeviceResponse):
                logger.info("SAS confirmed!")
            elif isinstance(resp, ToDeviceError):
                logger.error(f"Failed to confirm SAS: {resp}")
        else:
            logger.warning("No active SAS verification found.")

    async def verification_mac(self, event):
        """Handle verification MAC event."""
        logger.info(f"Verification MAC received: {event}")
        sas = self.client.get_active_sas(event.sender, event.from_device)
        if sas:
            resp = await self.client.confirm_key_verification(event.transaction_id)
            if isinstance(resp, ToDeviceResponse):
                logger.info("Device verified!")
            elif isinstance(resp, ToDeviceError):
                logger.error(f"Failed to verify device: {resp}")
        else:
            logger.warning("No active SAS verification found.")

    async def verification_cancel(self, event):
        """Handle verification cancel event."""
        logger.info(f"Verification canceled: {event}")
        try:
            await self.client.cancel_key_verification(event.transaction_id, reject=False)
            logger.info("Verification canceled successfully.")
        except Exception as e:
            logger.error(f"Error canceling verification: {e}")

def get_matrix_username():
    config_file = "config.json"
    with open(config_file) as f:
        config = json.load(f)
        return config[1]['matrix_username']

async def main():
    matrix_username = get_matrix_username()
    
    infinigpt = InfiniGPT()
    
    jwt_token = infinigpt._generate_jwt(matrix_username)
    
    os.environ['OPENAI_API_KEY'] = jwt_token
    
    infinigpt.initialize_openai(jwt_token)
    
    await infinigpt.main()

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())