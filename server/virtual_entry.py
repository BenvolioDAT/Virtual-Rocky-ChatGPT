# Entry point for optional PyInstaller build. Config remains beside the exe.
if __name__ == '__main__':
    import sys
    if '--screen-helper' in sys.argv:
        from desktop_vision.screen_bridge import main
    else:
        from brain.virtual import main
    main()
