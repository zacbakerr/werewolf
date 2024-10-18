from collections import defaultdict
from typing import Any, Dict

import os
import asyncio
import openai
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


class SentWerewolfAgent(IReactiveAgent):

    GAME_CHANNEL = "play-arena"
    WOLFS_CHANNEL = "wolf's-den"
    MODERATOR_NAME = "moderator"

    # These prompts can be filled with role-specific instructions to guide the agent's behavior
    WOLF_PROMPT = ""
    VILLAGER_PROMPT = ""
    SEER_PROMPT = ""
    DOCTOR_PROMPT = ""

    def __init__(self):
        # Basic initialization, further setup is done in __initialize__
        pass

    def __initialize__(self, name: str, description: str, config: dict = None):
        """
        Initialize the agent with its name, description, and configuration.
        This method is called after the agent is instantiated and sets up the agent's state.

        - name: The agent's name in the game (e.g., "vivek", "Luca", "Wei")
        - description: A brief description of the agent (e.g., "strong werewolf agent")
        - config: Additional configuration parameters
        """
        super().__initialize__(name, description, config)
        self._name = name
        self._description = description
        self.config = config
        self.role = None  # Will be set when the moderator assigns roles
        # Stores direct messages from moderator
        self.dirrect_messages = defaultdict(list)
        self.group_channel_messages = defaultdict(
            list)  # Stores messages from group channels
        self.openai_client = openai.OpenAI(
            api_key=os.environ.get("sentient_llm_key"),
            base_url=os.environ.get("sentient_hosted_llm_end_point")
        )

    async def async_notify(self, message: ActivityMessage):
        """
        Process incoming messages and update the agent's state.
        This method stores messages for later use in decision-making.

        - Direct messages are stored in self.dirrect_messages
        - Group messages are stored in self.group_channel_messages
        """
        if message.header.channel_type == MessageChannelType.DIRECT:
            user_messages = self.dirrect_messages.get(
                message.header.sender, [])
            user_messages.append(message.content.text)
            self.dirrect_messages[message.header.sender] = user_messages
            if (
                not len(user_messages) > 1
                and message.header.sender == self.MODERATOR_NAME
            ):
                self.role = self.find_my_role(message)
        else:
            group_messages = self.group_channel_messages.get(
                message.header.channel, [])
            group_messages.append(
                (message.header.sender, message.content.text))
            self.group_channel_messages[message.header.channel] = group_messages

    @retry(
        wait=wait_exponential(multiplier=1, min=20, max=300),
        stop=stop_after_attempt(5),
        retry=retry_if_exception_type(openai.RateLimitError),
    )
    def find_my_role(self, message):
        """
        Determine the agent's role based on the moderator's message.
        This method uses the OpenAI API to interpret the role assignment message.

        Roles in Werewolf:
        - Villager: The majority, trying to identify and eliminate werewolves
        - Wolf: A minority, attempting to eliminate villagers without being detected
        - Seer: A special villager who can check one player's identity each night
        - Doctor: A special villager who can protect one player from elimination each night
        """
        response = self.openai_client.chat.completions.create(
            model="meta.llama3-70b-instruct-v1:0",
            messages=[
                {
                    "role": "system",
                    "content": f"The user is playing a game of werewolf as user {self._name} or Mafia, help user with question with less then a line answer",
                },
                {
                    "role": "user",
                    "name": self._name,
                    "content": f"I have got message from moderator here about my role in the werewolf game, here is the message -> '{message.content.text}', what is my role , possible roles are 'wolf','villager','doctor' and 'seer'. answer me in few word",
                },
            ],
        )
        my_role_guess = response.choices[0].message.content
        if "wolf" in my_role_guess.lower():
            role = "wolf"
        elif "seer" in my_role_guess.lower():
            role = "seer"
        elif "doctor" in my_role_guess.lower():
            role = "doctor"
        else:
            role = "villager"
        return role

    async def async_respond(self, message: ActivityMessage):
        """
        Generate responses to incoming messages that require a reply.
        This method uses stored messages to make informed decisions.
        """
        if (
            message.header.channel_type == MessageChannelType.DIRECT
            and message.header.sender == self.MODERATOR_NAME
        ):
            self.dirrect_messages[message.header.sender].append(
                message.content.text)
            if self.role == "seer":
                response_message = self._get_response_for_seer_guess(message)
            elif self.role == "doctor":
                response_message = self._get_response_for_doctors_save(message)
            elif self.role == "wolf":
                response_message = self._get_response_for_wolf_elimination(
                    message)
            response = ActivityResponse(response=response_message)
        elif message.header.channel_type == MessageChannelType.GROUP:
            self.group_channel_messages[message.header.channel].append(
                (message.header.sender, message.content.text)
            )
            if message.header.channel == self.GAME_CHANNEL:
                response_message = (
                    self._get_discussion_message_or_vote_response_for_common_room(
                        message)
                )
            elif message.header.channel == self.WOLFS_CHANNEL:
                response_message = self._get_response_for_wolf_channel_to_kill_vilagers(
                    message)
            return ActivityResponse(response=response_message)

        return ActivityResponse(response=response_message)

    def _get_response_for_seer_guess(self, message):
        """
        Generate a response for the Seer's night action.

        This method should use stored messages to make an informed decision:
        - Check self.group_channel_messages[self.GAME_CHANNEL] for suspicious behavior
        - Use self.dirrect_messages[self.MODERATOR_NAME] for previous guesses and results

        Example implementation:
        moderator_messages = self.dirrect_messages[self.MODERATOR_NAME]
        day_discussions = self.group_channel_messages[self.GAME_CHANNEL]

        # Analyze day_discussions and moderator_messages to make an informed decision
        # Return a string with the chosen player to investigate
        return "I'm going to take a wild guess and say that [player_name] is a wolf."
        """
        pass

    def _get_response_for_doctors_save(self, message):
        """
        Generate a response for the Doctor's night action.

        This method should use stored messages to make an informed decision:
        - Check self.group_channel_messages[self.GAME_CHANNEL] for players under suspicion
        - Use self.dirrect_messages[self.MODERATOR_NAME] for previous save information

        Example implementation:
        moderator_messages = self.dirrect_messages[self.MODERATOR_NAME]
        day_discussions = self.group_channel_messages[self.GAME_CHANNEL]

        # Analyze day_discussions and moderator_messages to make an informed decision
        # Return a string with the chosen player to protect
        return "I will protect [player_name] tonight."
        """
        pass

    def _get_response_for_wolf_elimination(self, message):
        """
        Generate a response for the Wolf's night action to eliminate a villager.

        This method should use stored messages to make an informed decision:
        - Check self.group_channel_messages[self.GAME_CHANNEL] for potential targets
        - Use self.dirrect_messages[self.MODERATOR_NAME] for any relevant information from the moderator
        - Consider messages in self.group_channel_messages[self.WOLFS_CHANNEL] for coordination with other wolves

        Example implementation:
        moderator_messages = self.dirrect_messages[self.MODERATOR_NAME]
        day_discussions = self.group_channel_messages[self.GAME_CHANNEL]
        wolf_discussions = self.group_channel_messages[self.WOLFS_CHANNEL]

        # Analyze day_discussions, moderator_messages, and wolf_discussions to make an informed decision
        # Consider factors like:
        # - Players who seem suspicious of the wolves
        # - Players who might be the Seer or Doctor
        # - Suggestions from other wolves
        # - Past elimination patterns to avoid suspicion

        # Return a string with the chosen player to eliminate
        return "I vote to eliminate [player_name]."
        """
        pass

    def _get_discussion_message_or_vote_response_for_common_room(self, message):
        """
        Generate a response for day phase discussions or voting in the main game channel.

        This method should use stored messages to craft a strategic response:
        - Analyze self.group_channel_messages[self.GAME_CHANNEL] for the current discussion context
        - Use self.dirrect_messages[self.MODERATOR_NAME] for role-specific information
        - If the agent is a wolf, consider self.group_channel_messages[self.WOLFS_CHANNEL]

        Example implementation:
        day_discussions = self.group_channel_messages[self.GAME_CHANNEL]
        moderator_messages = self.dirrect_messages[self.MODERATOR_NAME]

        # Analyze day_discussions and moderator_messages to craft a strategic response
        # If wolf, also consider self.group_channel_messages[self.WOLFS_CHANNEL]
        # Return a string with the discussion contribution or vote
        return "I think [player_name] might be suspicious because [reason]."
        """
        pass

    def _get_response_for_wolf_channel_to_kill_vilagers(self, message):
        """
        Generate a response for Werewolves to choose a target during the night phase.

        This method should use stored messages to coordinate with other wolves:
        - Analyze self.group_channel_messages[self.WOLFS_CHANNEL] for other wolves' opinions
        - Consider self.group_channel_messages[self.GAME_CHANNEL] for potential high-value targets

        Example implementation:
        wolf_discussions = self.group_channel_messages[self.WOLFS_CHANNEL]
        day_discussions = self.group_channel_messages[self.GAME_CHANNEL]

        # Analyze wolf_discussions and day_discussions to choose a target
        # Return a string with the chosen player to eliminate
        return "I suggest we eliminate [player_name] because [reason]."
        """
        pass