def test_domain_package_imports() -> None:
    import domain.intelligence
    import domain.memory
    import domain.quality
    import domain.reports
    import domain.sources

    assert domain.intelligence is not None
    assert domain.memory is not None
    assert domain.quality is not None
    assert domain.reports is not None
    assert domain.sources is not None
