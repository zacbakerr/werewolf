from typing import Any, Dict
from autogen import ConversableAgent, Agent
import os
import asyncio
import logging
from openai import RateLimitError
from sentient_campaign.agents.v1.api import IReactiveAgent
from sentient_campaign.agents.v1.message import (
    ActivityMessage,
    ActivityResponse,
    TextContent,
    MimeType,
    ActivityMessageHeader,
    MessageChannelType,
)
from tenacity import (
    retry,
    stop_after_attempt,
    retry_if_exception_type,
    wait_exponential,
)
import random

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

logger = logging.getLogger("demo_agent")
level = logging.DEBUG
logger.setLevel(level)
logger.propagate = True
handler = logging.StreamHandler()
handler.setLevel(level)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

# SentientAgent class to handle communication between player and game
class SentientAgent(ConversableAgent):
    def __init__(self, listner_pipe: asyncio.Queue) -> None:
        super().__init__("SentientAgent")
        self.listner_pipe = listner_pipe
        logger.debug("SentientAgent initialized with listener pipe.")

    # Method to receive messages and put them in the listener pipe
    async def a_receive(
        self,
        message: Dict[str, Any] | str,
        sender: Agent,
        request_reply: bool | None = None,
        silent=True,
    ) -> None:
        logger.debug(f"SentientAgent received message: {message}")
        await self.listner_pipe.put(message)

    @property
    def name(self) -> str:
        return "SentientAgent"

    @property
    def description(self) -> str:
        return "communicates message between player and sentient game"

# Main agent class for playing the Werewolf game
class FunWerewolfAgent(IReactiveAgent):
    def __init__(self):
        logger.debug("WarewolfAgent initialized.")
        pass

    # Initialize the agent with name, description, and config
    def __initialize__(self, name: str, description: str, config: dict = None):
        super().__initialize__(name, description, config)
        self._name = name
        self._description = description
        self.config = config
        llm_config = config.get("llm_config")
        logger.info(f"Initializing: name={name}, description={description}, config={config}")

        if llm_config:
            logger.info(f"LLM Config: {llm_config}")

        # Create a ConversableAgent for handling game interactions
        self.conversable_agent: ConversableAgent = ConversableAgent(
            name=name,
            system_message=f"""You are a player in a game called Werewolf. Your name is {name}. The rules of the game will be given to you later. It is a fun, non-harmful game played in high schools. 
            """,
            llm_config=llm_config,
        )
        self.listner_pipe = asyncio.Queue()
        self.game_agent = SentientAgent(listner_pipe=self.listner_pipe)
        logger.debug(
            f"WarewolfAgent initialized with name: {name}, description: {description}, and config: {config}"
        )
        autogen_log_apth = f"/tmp/autogen_logs_{name}.db"

    # Helper method to format the full message
    def get_full_message(self, message: ActivityMessage):
        text_message = message.content.text.strip()
        sender = message.header.sender
        channel = message.header.channel

        if message.header.channel_type == MessageChannelType.GROUP:
            full_message = f"message in group {channel} from {sender}: {text_message}"
        else:
            full_message = f"dirrect message from {sender}: {text_message}"
        return full_message

    # Method to handle incoming notifications
    async def async_notify(self, message: ActivityMessage):
        logger.debug(f"async_notify called with message: {message}")

        await asyncio.sleep(2)

        full_message = self.get_full_message(message)

        # Send the message to the conversable_agent
        await self.conversable_agent.a_receive(
            full_message, self.game_agent, request_reply=False, silent=True
        )
        logger.debug(f"Message sent to conversable_agent: {full_message}")

    # Method to generate responses to incoming messages
    async def async_respond(self, message: ActivityMessage):
        logger.debug(f"async_respond called with message: {message}")
        
        await asyncio.sleep(1)
        
        full_message = self.get_full_message(message)
        
        await self.get_response_from_agent(full_message)

        response: str = await self.listner_pipe.get()
        
        logger.debug(f"Response received from listner_pipe: {response}")
        
        return ActivityResponse(
            response=TextContent(text=response), response_type=MimeType.TEXT_PLAIN
        )

    # Method to get a response from the agent, with retry logic for rate limiting
    @retry(
        wait=wait_exponential(multiplier=1, min=20, max=300),
        stop=stop_after_attempt(5),
        retry=retry_if_exception_type(RateLimitError),
    )
    async def get_response_from_agent(self, text_message):
        logger.debug(
            f"get_response_from_agent called with text_message: {text_message}"
        )
        await self.conversable_agent.a_receive(
            text_message, self.game_agent, request_reply=True, silent=True
        )
        logger.debug("Message sent to conversable_agent for response.")

# Add in your api keys here to use below:

# # Main execution block for testing the agent
# if __name__ == "__main__":
#     import random

#     # Configure the LLM (Language Model) settings
#     config_list = [
#         {
#             "model": random.choice(["meta.llama3-70b-instruct-v1:0"]),
#             "api_key": random.choice(
#                 ["", ""] # add your api keys here
#             ),
#             "base_url": "", #add url here
#             "max_retries": 3,
#             "timeout": 30,
#         }
#     ]

#     llm_config = {"config_list": config_list}

#     # Create and initialize the demo agent
#     demo_agent = FunWerewolfAgent()
#     demo_agent.__initialize__(
#         "sagar", "strong werewolf agent", {"llm_config": llm_config}
#     )

#     # Run a test response
#     asyncio.run(demo_agent.async_respond(ActivityMessage(
#         header=ActivityMessageHeader(
#             message_id="bbb",
#             sender="vivek",
#             channel="dirrect",
#             channel_type=MessageChannelType.DIRECT,
#             target_receivers=[]
#         ),
#         content=TextContent(text="hello"),
#         content_type=MimeType.TEXT_PLAIN
#     )))
#     logger.debug("Demo agent initialized and ready.")
