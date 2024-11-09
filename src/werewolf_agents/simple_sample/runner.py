import os
import json
from dotenv import load_dotenv
from pathlib import Path
load_dotenv()

from sentient_campaign.activity_runner.runner import WerewolfCampaignActivityRunner, PlayerAgentConfig

# Create results directory if it doesn't exist
Path("game_results").mkdir(parents=True, exist_ok=True)
# Ensure transcripts directory exists
Path("transcripts").mkdir(parents=True, exist_ok=True)

runner = WerewolfCampaignActivityRunner()
agent_config = PlayerAgentConfig(
    player_name="James", # select a name for your agent
                
    #TODO: IMPORTANT!! After building your agent for the first time, you must update this path:
    agent_wheel_path="C:/Users/zacat/OneDrive/Desktop/werewolf-template/src/werewolf_agents/simple_sample/dist/simplewolf-0.0.1-py3-none-any.whl", 
    module_path="agent/super_simple.py",
    agent_class_name="SimpleReactiveAgent",
    agent_config_file_path="config.yaml" 
)
players_sentient_llm_api_keys = [os.getenv("MY_UNIQUE_API_KEY")]

# Run the game and save the results
game_results = runner.run_against_standard_agents(
    agent_config,
    players_sentient_llm_api_keys,
    path_to_final_transcript_dump="transcripts",
    force_rebuild_agent_image=True
)

# Save the game results to a JSON file in game_results directory
results_file = os.path.join("game_results", f"game_results_{game_results['activity_id']}.json")
with open(results_file, 'w') as f:
    json.dump(game_results, f, indent=2)

print(f"Game results saved to: {results_file}")

# Use this URL to watch the game live, please wait till the game gets going, otherwise it will say incorrect credentials
# Safari not supported, use Chrome. 
# URL to hosted game messenger client: https://hydrogen.sentient.xyz/#/login

# IF THIS MESSENGER CLIENT IS NOT WORKING, MAKE SURE YOU ARE USING SAFARI, AND WAITING. IF STILL NOT WORKING SEE DOCS.