from sentient_campaign.activity_runner.runner import WerewolfCampaignActivityRunner, PlayerAgentConfig

runner = WerewolfCampaignActivityRunner()
agent_config = PlayerAgentConfig(
    player_name="YourAgentName",
    agent_wheel_path="src/werewolf_agents/autogen_sample/config.yaml",
    module_path="src/werewolf_agents/autogen_sample/autogen_single.py",
    agent_class_name="FunWerewolfAgent",
    agent_config_file_path="src/werewolf_agents/autogen_sample/config.yaml"
)
players_sentient_llm_api_keys = []
activity_id = runner.run_locally(
    agent_config,
    players_sentient_llm_api_keys,
    path_to_final_transcript_dump="src/transcripts",
    force_rebuild_agent_image=False
)