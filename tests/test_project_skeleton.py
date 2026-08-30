def test_project_packages_import() -> None:
    import backend.foundation
    import backend.layers.signal
    import backend.research
    import framework
    import infrastructure.storage
    import interfaces

    assert framework is not None
    assert backend.foundation is not None
    assert backend.layers.signal is not None
    assert backend.research is not None
    assert infrastructure.storage is not None
    assert interfaces is not None
