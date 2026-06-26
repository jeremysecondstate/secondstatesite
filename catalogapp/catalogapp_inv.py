try:
    from catalogapp.catalogapp_inv_ui import main
except ImportError:
    from catalogapp_inv_ui import main


if __name__ == "__main__":
    main()
