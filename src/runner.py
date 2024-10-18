# from sentient_campaign.activity_runner.runner import WerewolfCampaignActivityRunner, PlayerAgentConfig

# runner = WerewolfCampaignActivityRunner()
# agent_config = PlayerAgentConfig(
#     player_name="YourAgentName",
#     agent_wheel_path="/path/to/your/agent.whl",
#     module_path="your.module.path",
#     agent_class_name="YourAgentClass",
#     agent_config_file_path="/path/to/agent_config.yaml"
# )
# players_sentient_llm_api_keys = []
# activity_id = runner.run_locally(
#     agent_config,
#     players_sentient_llm_api_keys,
#     path_to_final_transcript_dump="/path/to/save/transcripts",
#     force_rebuild_agent_image=False
# )