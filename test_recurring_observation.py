from recurring_observation import RecurringObservationConfig, validate_config


def test_default_schedule_is_finite_dry_run_and_one_hour_cadence():
    config = RecurringObservationConfig()
    assert config.max_cycles == 6
    assert config.cadence_seconds == 3600
    assert config.execute is False
    assert config.scheduler == "none"
    assert validate_config(config) == []


def test_schedule_rejects_unbounded_or_fast_execution():
    config = RecurringObservationConfig(max_cycles=0, cadence_seconds=60, execute=True, scheduler="cron")
    errors = validate_config(config)
    assert "max_cycles must be between 1 and 24" in errors
    assert "cadence_seconds must be at least 3600" in errors
    assert "scheduler must be none for bounded local observation" in errors
    assert "execute must remain false until separate recurring-loop approval" in errors
