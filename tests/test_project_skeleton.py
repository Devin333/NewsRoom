def test_project_packages_import() -> None:
    import core.framework
    import domain
    import interfaces
    import storage
    import workflows.daily_intelligence

    assert core.framework is not None
    assert domain is not None
    assert interfaces is not None
    assert storage is not None
    assert workflows.daily_intelligence is not None
