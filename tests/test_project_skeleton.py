def test_project_packages_import() -> None:
    import business.foundation
    import business.layers.signal
    import business.research
    import framework
    import infrastructure.storage
    import interfaces

    assert framework is not None
    assert business.foundation is not None
    assert business.layers.signal is not None
    assert business.research is not None
    assert infrastructure.storage is not None
    assert interfaces is not None
