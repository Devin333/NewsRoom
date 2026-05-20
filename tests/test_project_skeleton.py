def test_project_packages_import() -> None:
    import framework
    import business.foundation
    import business.layers.signal
    import infrastructure.storage
    import interfaces
    import business.boards.cross_board.workflows.daily_intelligence

    assert framework is not None
    assert business.foundation is not None
    assert business.layers.signal is not None
    assert infrastructure.storage is not None
    assert interfaces is not None
    assert business.boards.cross_board.workflows.daily_intelligence is not None
