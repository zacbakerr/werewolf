from typing import Any, Dict, List
from autogen import ConversableAgent, Agent, runtime_logging
import os, json, re

import asyncio
import logging
from collections import defaultdict
import openai
from openai import RateLimitError, OpenAI
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

GAME_CHANNEL = "play-arena"
WOLFS_CHANNEL = "wolf's-den"
MODERATOR_NAME = "moderator"
MODEL_NAME = "Llama31-70B-Instruct"

# Configure logging
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

class CoTAgent(IReactiveAgent):
    # input -> thoughts -> init action -> reflection -> final action
    GENERAL_NON_WOLF_TIPS = """Key strategies for non-werewolf roles (villager/seer/doctor):
    1. In early game (first 1-2 rounds), avoid making direct accusations. Instead say "We don't have enough information yet to make strong conclusions, but..."
    2. In early game, focus on observing and commenting on general behaviors rather than accusing specific players
    3. When agreeing/disagreeing with others, always explain your reasoning to avoid appearing like you're blindly following
    4. Track voting patterns and who leads votes against whom
    5. When asked for a final vote by moderator, respond with just the name
    6. Pay attention to who makes early aggressive accusations - they might be wolves trying to eliminate threats
    7. Consider probability - as roles are revealed, update your suspicions accordingly
    8. Look for verbal slip-ups where players accidentally reveal their role (e.g., "as a wolf..." or mentioning wolf-specific knowledge)
    9. If someone is heavily suspected by the majority, it's usually safer to vote with the group
    """

    WOLF_PROMPT = """You are a wolf in a game of Werewolf. Your goal is to eliminate villagers without being detected. Consider the following:
    1. NEVER mention anything about being a wolf, the wolf team, or wolf pact in public messages
    2. In early rounds, be as passive as other villagers - avoid making any accusations
    3. If your werewolf teammate is under heavy suspicion, DO NOT defend them - vote with the majority to avoid suspicion
    4. Never use words like "we" or "us" when referring to wolves, even in the wolf channel
    5. Act exactly like a confused villager would - express uncertainty, ask questions
    6. When asked for a vote by the moderator, respond with just the name
    7. Prioritize eliminating the seer and doctor if you suspect them, but don't be obvious about it
    8. Create subtle misdirection by agreeing with villagers' suspicions about others
    9. If someone is strongly suspected by the village, always vote with the majority
    10. Remember: your survival is more important than defending your teammate
    """

    VILLAGER_PROMPT = f"""{GENERAL_NON_WOLF_TIPS}
    You are a villager in a game of Werewolf. Additional considerations:
    1. Look for players who make aggressive early-game accusations
    2. Watch for players who defend suspected werewolves
    3. Pay attention to verbal slip-ups that might reveal someone's role
    4. Trust players who successfully identify werewolves
    5. If the majority suspects someone, it's usually safer to vote with them
    """

    SEER_PROMPT = f"""{GENERAL_NON_WOLF_TIPS}
    You are the seer in a game of Werewolf. Additional considerations:
    1. NEVER investigate the same player twice - your power gives you absolute certainty
    2. NEVER vote for confirmed villagers
    3. Keep track of who you've checked and their roles
    4. Only reveal yourself when you've confirmed a werewolf
    5. When you find a werewolf, immediately reveal yourself and their identity
    6. Watch for verbal slip-ups from players that might reveal their role
    """

    DOCTOR_PROMPT = f"""{GENERAL_NON_WOLF_TIPS}
    You are the doctor in a game of Werewolf. Additional considerations:
    1. Prioritize protecting confirmed villagers and suspected seer
    2. Vary your protection pattern to be unpredictable
    3. Track who successfully identifies werewolves - they're likely trustworthy
    4. Keep your role hidden unless absolutely necessary
    5. Watch for verbal slip-ups from players that might reveal their role
    """

    def __init__(self):
        logger.debug("WerewolfAgent initialized.")
        self.role_probabilities = {}  # Will be initialized in __initialize__

    def __initialize__(self, name: str, description: str, config: dict = None):
        super().__initialize__(name, description, config)
        self._name = name
        self._description = description
        self.MODERATOR_NAME = MODERATOR_NAME
        self.WOLFS_CHANNEL = WOLFS_CHANNEL
        self.GAME_CHANNEL = GAME_CHANNEL
        self.config = config
        self.have_thoughts = True
        self.have_reflection = True
        self.role = None
        self.direct_messages = defaultdict(list)
        self.group_channel_messages = defaultdict(list)
        self.seer_checks = {}  # To store the seer's checks and results
        self.game_history = []  # To store the interwoven game history
        self.llm_config = self.sentient_llm_config["config_list"][0]
        self.openai_client = OpenAI(
            api_key=self.llm_config["api_key"],
            base_url=self.llm_config["llm_base_url"],
        )
        self.model = self.llm_config["llm_model_name"]
        logger.info(f"WerewolfAgent initialized with name: {name}, description: {description}, and config: {config}")

        self.game_intro = None
        self.role_probabilities = {
            'werewolf': {},
            'seer': {},
            'doctor': {},
            'villager': {}
        }

    def _is_early_game(self):
        # Count number of voting rounds that have occurred
        vote_count = sum(1 for msg in self.game_history if "moderator" in msg.lower() and "vote" in msg.lower())
        return vote_count < 2

    async def async_notify(self, message: ActivityMessage):
        logger.info(f"ASYNC NOTIFY called with message: {message}")
        if message.header.channel_type == MessageChannelType.DIRECT:
            user_messages = self.direct_messages.get(message.header.sender, [])
            user_messages.append(message.content.text)
            self.direct_messages[message.header.sender] = user_messages
            self.game_history.append(f"[From - {message.header.sender}| To - {self._name} (me)| Direct Message]: {message.content.text}")
            if not len(user_messages) > 1 and message.header.sender == self.MODERATOR_NAME:
                self.role = self.find_my_role(message)
                logger.info(f"Role found for user {self._name}: {self.role}")
        else:
            group_messages = self.group_channel_messages.get(message.header.channel, [])
            group_messages.append((message.header.sender, message.content.text))
            self.group_channel_messages[message.header.channel] = group_messages
            self.game_history.append(f"[From - {message.header.sender}| To - Everyone| Group Message in {message.header.channel}]: {message.content.text}")
            if message.header.channel == self.GAME_CHANNEL and message.header.sender == self.MODERATOR_NAME and not self.game_intro:
                self.game_intro = message.content.text
        logger.info(f"message stored in messages {message}")

    def get_interwoven_history(self, include_wolf_channel=False):
        return "\n".join([
            event for event in self.game_history
            if include_wolf_channel or not event.startswith(f"[{self.WOLFS_CHANNEL}]")
        ])

    @retry(
        wait=wait_exponential(multiplier=1, min=20, max=300),
        stop=stop_after_attempt(5),
        retry=retry_if_exception_type(openai.RateLimitError),
    )
    def find_my_role(self, message):
        response = self.openai_client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": f"The user is playing a game of werewolf as user {self._name}, help the user with question with less than a line answer",
                },
                {
                    "role": "user",
                    "name": self._name,
                    "content": f"You have got message from moderator here about my role in the werewolf game, here is the message -> '{message.content.text}', what is your role? possible roles are 'wolf','villager','doctor' and 'seer'. answer in a few words.",
                },
            ],
        )
        my_role_guess = response.choices[0].message.content
        logger.info(f"my_role_guess: {my_role_guess}")
        if "villager" in my_role_guess.lower():
            role = "villager"
        elif "seer" in my_role_guess.lower():
            role = "seer"
        elif "doctor" in my_role_guess.lower():
            role = "doctor"
        else:
            role = "wolf"
        return role

    async def async_respond(self, message: ActivityMessage):
        logger.info(f"ASYNC RESPOND called with message: {message}")
        if message.header.channel_type == MessageChannelType.DIRECT and message.header.sender == self.MODERATOR_NAME:
            self.direct_messages[message.header.sender].append(message.content.text)
            if self.role == "seer":
                response_message = self._get_response_for_seer_guess(message)
            elif self.role == "doctor":
                response_message = self._get_response_for_doctors_save(message)
            response = ActivityResponse(response=response_message)
            self.game_history.append(f"[From - {message.header.sender}| To - {self._name} (me)| Direct Message]: {message.content.text}")
            self.game_history.append(f"[From - {self._name} (me)| To - {message.header.sender}| Direct Message]: {response_message}")    
        elif message.header.channel_type == MessageChannelType.GROUP:
            self.group_channel_messages[message.header.channel].append(
                (message.header.sender, message.content.text)
            )
            if message.header.channel == self.GAME_CHANNEL:
                # Update probabilities based on new information
                self._update_probabilities_from_discussion(message)
                # If this is a vote request, return the most likely werewolf
                if "vote" in message.content.text.lower() and message.header.sender == self.MODERATOR_NAME:
                    response_message = self._get_most_likely_werewolf()
                else:
                    response_message = self._get_discussion_message_or_vote_response_for_common_room(message)
            elif message.header.channel == self.WOLFS_CHANNEL:
                response_message = self._get_response_for_wolf_channel_to_kill_villagers(message)
            self.game_history.append(f"[From - {message.header.sender}| To - {self._name} (me)| Group Message in {message.header.channel}]: {message.content.text}")
            self.game_history.append(f"[From - {self._name} (me)| To - {message.header.sender}| Group Message in {message.header.channel}]: {response_message}")
                
        return ActivityResponse(response=response_message)

    def _get_inner_monologue(self, role_prompt, game_situation, specific_prompt):
        prompt = f"""{role_prompt}

Current game situation (including your past thoughts and actions): 

{game_situation}



{specific_prompt}"""

        response = self.openai_client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": f"You are a {self.role} in a Werewolf game."},
                {"role": "user", "content": prompt}
            ]
        )
        inner_monologue = response.choices[0].message.content
        # self.game_history.append(f"\n [My Thoughts]: {inner_monologue}")

        logger.info(f"My Thoughts: {inner_monologue}")

        return inner_monologue

    def _get_final_action(self, role_prompt, game_situation, inner_monologue, action_type):
        prompt = f"""{role_prompt}

Current game situation (including past thoughts and actions): 

{game_situation}



Your thoughts:

{inner_monologue}



Based on your thoughts and the current situation, what is your {action_type}? Respond with only the {action_type} and no other sentences/thoughts. If it is a dialogue response, you can provide the full response that adds to the discussions so far. For all other cases a single sentence response is expected. If you are in the wolf-group channel, the sentence must contain the name of a person you wish to eliminate, and feel free to change your mind so that there is consensus. If you are in the game-room channel, the sentence must contain your response or vote, and it must be a vote to eliminate someone if the game moderator has recently messaged you asking for a vote, and also feel free to justify your vote, and later change your mind when the final vote count happens. You can justify any change of mind too. If the moderator for the reason behind the vote, you must provide the reason in the response."""

        response = self.openai_client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": f"You are a {self.role} in a Werewolf game. Provide your final {action_type}."},
                {"role": "user", "content": prompt}
            ]
        )

        logger.info(f"My initial {action_type}: {response.choices[0].message.content}")
        initial_action = response.choices[0].message.content
        # do another run to reflect on the final action and do a sanity check, modify the response if need be
        prompt = f"""{role_prompt}

Current game situation (including past thoughts and actions):

{game_situation}



Your thoughts:

{inner_monologue}



Your initial action:

{response.choices[0].message.content}



Reflect on your final action given the situation and provide any criticisms. Answer the folling questions:

1. What is my name and my role ? 

2. Does my action align with my role and am I revealing too much about myself in a public channel? Does my action harm my team or my own interests?

3. Is my action going against what my objective is in the game?

3. How can I improve my action to better help the agents on my team and help me survive?"""

        response = self.openai_client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": f"You are a {self.role} in a Werewolf game. Reflect on your final action."},
                {"role": "user", "content": prompt}
            ]
        )

        logger.info(f"My reflection: {response.choices[0].message.content}")

         # do another run to reflect on the final action and do a sanity check, modify the response if need be
        prompt = f"""{role_prompt}

Current game situation (including past thoughts and actions):

{game_situation}



Your thoughts:

{inner_monologue}



Your initial action:

{initial_action}



Your reflection:

{response.choices[0].message.content}



Based on your thoughts, the current situation, and your reflection on the initial action, what is your absolute final {action_type}? Respond with only the {action_type} and no other sentences/thoughts. If it is a dialogue response, you can provide the full response that adds to the discussions so far. For all other cases a single sentence response is expected. If you are in the wolf-group channel, the sentence must contain the name of a person you wish to eliminate, and feel free to change your mind so that there is consensus. If you are in the game-room channel, the sentence must contain your response or vote, and it must be a vote to eliminate someone if the game moderator has recently messaged you asking for a vote, and also feel free to justify your vote, and later change your mind when the final vote count happens. You can justify any change of mind too. If the moderator for the reason behind the vote, you must provide the reason in the response. If the moderator asked for the vote, you must mention at least one name to eliminate. If the moderator asked for a final vote, you must answer in a single sentence the name of the person you are voting to eliminate even if you are not sure."""

        response = self.openai_client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": f"You are a {self.role} in a Werewolf game. Provide your final {action_type}."},
                {"role": "user", "content": prompt}
            ]
        )

        return response.choices[0].message.content.strip("\n ")

    def _summarize_game_history(self):
        self.detailed_history = "\n".join(self.game_history)
        # send the llm the previous summary of each of the other players and suspiciona nd information, the detailed chats of this day or night
        # llm will summarize the game history and provide a summary of the game so far
        # summarized game history is used for current situation
        pass

    def _get_response_for_seer_guess(self, message):
        seer_checks_info = "\n".join([f"Checked {player}: {result}" for player, result in self.seer_checks.items()])
        game_situation = f"{self.get_interwoven_history()}\n\nMy past seer checks:\n{seer_checks_info}"

        specific_prompt = """think through your response by answering the following step-by-step:

1. What new information has been revealed in recent conversations?

2. Based on the game history, who seems most suspicious or important to check?

3. How can I use my seer ability most effectively without revealing my role?

4. What information would be most valuable for the village at this point in the game?

5. How can I guide the discussion during the day subtly to help the village? Should I reveal my role at this point?"""

        inner_monologue = self._get_inner_monologue(self.SEER_PROMPT, game_situation, specific_prompt)

        action = self._get_final_action(self.SEER_PROMPT, game_situation, inner_monologue, "choice of player to investigate")

        return action

    def _get_response_for_doctors_save(self, message):
        game_situation = self.get_interwoven_history()

        specific_prompt = """think through your response by answering the following step-by-step:

1. Based on recent discussions, who seems to be in the most danger?

2. Have I protected myself recently, or do I need to consider self-protection?

3. Are there any players who might be the Seer or other key roles that I should prioritize?

4. How can I vary my protection pattern to avoid being predictable to the werewolves?

5. How can I contribute to the village discussions with or without revealing my role? Should I reveal my role at this point?"""

        inner_monologue = self._get_inner_monologue(self.DOCTOR_PROMPT, game_situation, specific_prompt)

        action = self._get_final_action(self.DOCTOR_PROMPT, game_situation, inner_monologue, "choice of player to protect")        
        return action

    def _get_discussion_message_or_vote_response_for_common_room(self, message):
        # Check if this is a vote request from moderator
        is_vote_request = "vote" in message.content.text.lower() and message.header.sender == self.MODERATOR_NAME
        
        if is_vote_request:
            # For vote requests, just return the name
            role_prompt = getattr(self, f"{self.role.upper()}_PROMPT", self.VILLAGER_PROMPT)
            game_situation = self.get_interwoven_history()
            inner_monologue = self._get_inner_monologue(role_prompt, game_situation, "Who should I vote for based on current information?")
            return self._get_final_action(role_prompt, game_situation, inner_monologue, "vote")
        
        # For regular discussion
        if self._is_early_game():
            specific_prompt = """Remember this is early game. Focus on:
            1. Starting with "We don't have enough information yet to make strong conclusions, but..."
            2. Making general observations about behaviors rather than specific accusations
            3. Thoughtfully agreeing or disagreeing with others' points
            4. Avoiding being the first to accuse anyone"""
        else:
            specific_prompt = """think through your response by answering:
            1. What important information has been shared?
            2. Who seems suspicious or trustworthy based on behavior patterns?
            3. What evidence can I share without revealing my role?
            4. How can I guide the discussion helpfully?"""

        role_prompt = getattr(self, f"{self.role.upper()}_PROMPT", self.VILLAGER_PROMPT)

        game_situation = self.get_interwoven_history()

        specific_prompt = """think through your response by answering the following step-by-step:

1. What important information has been shared in the recent discussions?

2. Based on the game history, who seems most suspicious or trustworthy?

3. What evidence or observations can I share to help the village without revealing my role?

4. How can I guide the discussion in a helpful direction based on what I know?

5. If it's time to vote, who should I vote for and why, considering all the information available?

6. How do I respond if accused during the day without revealing my role?"""

        inner_monologue = self._get_inner_monologue(role_prompt, game_situation, specific_prompt)

        action = self._get_final_action(role_prompt, game_situation, inner_monologue, "vote and discussion point which includes reasoning behind your vote")        
        return action

    def _get_response_for_wolf_channel_to_kill_villagers(self, message):
        if self.role != "wolf":
            return "I am not a werewolf and cannot participate in this channel."

        game_situation = self.get_interwoven_history(include_wolf_channel=True)

        specific_prompt = """think through your response by answering the following step-by-step:

1. Based on the game history, who are the most dangerous villagers to our werewolf team?

2. Who might be the Seer or Doctor based on their behavior and comments?

3. Which potential target would be least likely to raise suspicion if eliminated?

4. How can we coordinate our actions with other werewolves to maximize our chances of success?

5. Arrive at a consensus for the target and suggest it to the group. Always make suggestions to eliminate at least one person.

6. How can we defend ourselves if accused during the day without revealing our roles?"""

        inner_monologue = self._get_inner_monologue(self.WOLF_PROMPT, game_situation, specific_prompt)

        action = self._get_final_action(self.WOLF_PROMPT, game_situation, inner_monologue, "suggestion for target")        
        return action

    def _initialize_probabilities(self, player_names: List[str]):
        """Initialize probabilities based on number of players and known roles"""
        num_players = len(player_names)
        num_werewolves = 2  # Assuming 2 werewolves in game

        # Initial probabilities
        werewolf_prob = num_werewolves / num_players
        special_role_prob = 1 / num_players  # For seer and doctor
        villager_prob = (num_players - num_werewolves - 2) / num_players

        for player in player_names:
            if player != self._name:  # Don't include self in probabilities
                self.role_probabilities['werewolf'][player] = werewolf_prob
                self.role_probabilities['seer'][player] = special_role_prob
                self.role_probabilities['doctor'][player] = special_role_prob
                self.role_probabilities['villager'][player] = villager_prob

    def _normalize_probabilities(self, role: str):
        """Ensure probabilities sum to 1 for each role"""
        total = sum(self.role_probabilities[role].values())
        if total > 0:
            for player in self.role_probabilities[role]:
                self.role_probabilities[role][player] /= total

    def _update_player_role_probability(self, player: str, confirmed_role: str):
        """Update probabilities when a player's role is confirmed"""
        if player in self.role_probabilities['werewolf']:
            # Set all probabilities to 0 except for confirmed role
            for role in self.role_probabilities:
                self.role_probabilities[role][player] = 1.0 if role == confirmed_role else 0.0

            # Normalize probabilities for remaining players
            for role in self.role_probabilities:
                self._normalize_probabilities(role)

    def _get_most_likely_werewolf(self) -> str:
        """Return the player with highest werewolf probability"""
        if not self.role_probabilities['werewolf']:
            return None
        return max(self.role_probabilities['werewolf'].items(), key=lambda x: x[1])[0]

    def _update_probabilities_from_discussion(self, message: ActivityMessage):
        """Update probabilities based on new information from discussions"""
        prompt = f"""Given the current game situation and probabilities:

        {self.get_interwoven_history()}

        

        Current probabilities for each player being a werewolf:

        {self.role_probabilities['werewolf']}

        

        Based on the new message:

        {message.content.text}

        

        How should these probabilities be adjusted? Consider:

        1. Voting patterns and accusations

        2. Defense of suspected werewolves

        3. Verbal slip-ups

        4. Quality of arguments

        

        Respond with a dictionary of probability adjustments (positive or negative) for each player."""

        response = self.openai_client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are analyzing werewolf game probabilities."},
                {"role": "user", "content": prompt}
            ]
        )

        # Parse adjustments from LLM response and apply them
        try:
            adjustments = eval(response.choices[0].message.content)
            for player, adjustment in adjustments.items():
                if player in self.role_probabilities['werewolf']:
                    self.role_probabilities['werewolf'][player] += adjustment
            self._normalize_probabilities('werewolf')
        except:
            logger.error("Failed to parse probability adjustments from LLM")


