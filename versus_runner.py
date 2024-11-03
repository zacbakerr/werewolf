from sentient_campaign.activity_runner.runner import WerewolfCampaignActivityRunner, PlayerAgentConfig, SentientWerewolfRoles
from transcript.reorg_files import reorg_files
import os
from typing import Dict, List
import random

# Default agent configurations
AGENT_CONFIGS = {
    "cot": {
        "wheel_path": "src/werewolf_agents/cot_sample/dist/cot_agent.whl",
        "module_path": "src.werewolf_agents.cot_sample.agent.main",
        "config_path": "src/werewolf_agents/cot_sample/config.yaml",
        "agent_class": "CoTAgent"
    },
    "autogen": {
        "wheel_path": "src/werewolf_agents/autogen_sample/dist/autogen_agent.whl",
        "module_path": "src.werewolf_agents.autogen_sample.agent.main",
        "config_path": "src/werewolf_agents/autogen_sample/config.yaml",
        "agent_class": "FunWerewolfAgent"
    },
    "simple": {
        "wheel_path": "src/werewolf_agents/simple_sample/dist/simple_agent.whl",
        "module_path": "src.werewolf_agents.simple_sample.agent.main",
        "config_path": "src/werewolf_agents/simple_sample/config.yaml",
        "agent_class": "SimpleReactiveAgent"
    }
}

# Default role distribution
DEFAULT_ROLE_DISTRIBUTION = {
    "wolves": {"agent_type": "cot", "count": 2},
    "villagers": {"agent_type": "autogen", "count": 4},
    "seer": {"agent_type": "simple", "count": 1},
    "doctor": {"agent_type": "simple", "count": 1}
}

def create_game_config(
    role_distribution: Dict = None,
    player_names: List[str] = None
) -> tuple:
    """Creates game configuration based on provided distribution or defaults"""
    
    role_distribution = role_distribution or DEFAULT_ROLE_DISTRIBUTION
    default_names = ["frodo", "samwise", "meriadoc", "peregrin", "bilbo", "hamfast", "fredegar", "lotho"]
    player_names = player_names or default_names

    # Validate total players
    total_players = sum(role["count"] for role in role_distribution.values())
    if total_players != 8 or len(player_names) != 8:
        raise ValueError("Total number of players must be 8")

    # Create role mapping
    roles = []
    for role_type, config in role_distribution.items():
        role_enum = getattr(SentientWerewolfRoles, role_type.upper().rstrip('s'))
        roles.extend([role_enum] * config["count"])

    # Shuffle roles for all names
    random.shuffle(roles)
    player_roles = dict(zip(player_names, roles))

    # Create agent configs
    your_agents = []
    current_idx = 0
    for role_type, config in role_distribution.items():
        agent_type = config["agent_type"]
        agent_config = AGENT_CONFIGS[agent_type]
        
        for _ in range(config["count"]):
            your_agents.append(PlayerAgentConfig(
                player_name=player_names[current_idx],
                agent_wheel_path=agent_config["wheel_path"],
                module_path=agent_config["module_path"],
                agent_class_name=agent_config["agent_class"],
                agent_config_file_path=agent_config["config_path"]
            ))
            current_idx += 1

    return your_agents, player_roles

# Example custom configuration (optional)
custom_distribution = {
    "wolves": {"agent_type": "cot", "count": 2},
    "villagers": {"agent_type": "autogen", "count": 4},
    "seer": {"agent_type": "simple", "count": 1},
    "doctor": {"agent_type": "simple", "count": 1}
}

# Create game configuration (using either default or custom)
your_agents, player_roles = create_game_config(
    # role_distribution=custom_distribution  # Uncomment to use custom distribution
)

# Run the game
runner = WerewolfCampaignActivityRunner(com_server_port=8008)

game_result = runner.run_with_your_agents(
    your_agents,
    players_sentient_llm_api_keys=["sk-k_kwMIIjKhlvd31zSLVQGw"],
    path_to_final_transcript_dump="transcript",
    player_roles=player_roles,
    force_rebuild_agent_images=False
)

activity_id = game_result.get("activity_id")
print(f"Activity completed with ID: {activity_id}")
# print game result into log file
with open("game_result_{0}.log".format(activity_id), "w") as f:
    f.write(str(game_result))

reorg_files("transcript", "game_result_{0}.log".format(activity_id))


