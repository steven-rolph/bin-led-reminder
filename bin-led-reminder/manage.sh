#!/bin/bash

SERVICE_NAME="bin-led-reminder"

show_usage() {
    echo "Bin LED Reminder Service Management"
    echo ""
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  start     Start the service"
    echo "  stop      Stop the service"
    echo "  restart   Restart the service"
    echo "  status    Show service status"
    echo "  logs      Show live logs"
    echo "  enable    Enable auto-start on boot"
    echo "  disable   Disable auto-start on boot"
    echo "  test      Test run (foreground, Ctrl+C to stop)"
    echo "  clear-errors  Clear error state and restart"
    echo ""
    echo "Web UI commands:"
    echo "  webui start    Start the web UI service"
    echo "  webui stop     Stop the web UI service"
    echo "  webui restart  Restart the web UI service"
    echo "  webui status   Show web UI service status"
    echo "  webui logs     Show live web UI logs"
    echo ""
}

case "$1" in
    start)
        echo "🚀 Starting $SERVICE_NAME service..."
        sudo systemctl start $SERVICE_NAME
        sudo systemctl status $SERVICE_NAME --no-pager
        ;;
    stop)
        echo "🛑 Stopping $SERVICE_NAME service..."
        sudo systemctl stop $SERVICE_NAME
        echo "✅ Service stopped"
        ;;
    restart)
        echo "🔄 Restarting $SERVICE_NAME service..."
        sudo systemctl restart $SERVICE_NAME
        sudo systemctl status $SERVICE_NAME --no-pager
        ;;
    status)
        echo "📊 Service status:"
        sudo systemctl status $SERVICE_NAME --no-pager
        echo ""
        echo "📈 Recent logs:"
        sudo journalctl -u $SERVICE_NAME --no-pager -n 10
        ;;
    logs)
        echo "📖 Live logs (Ctrl+C to exit):"
        sudo journalctl -u $SERVICE_NAME -f
        ;;
    enable)
        echo "⚡ Enabling auto-start on boot..."
        sudo systemctl enable $SERVICE_NAME
        echo "✅ Service will now start automatically on boot"
        ;;
    disable)
        echo "🚫 Disabling auto-start on boot..."
        sudo systemctl disable $SERVICE_NAME
        echo "✅ Service will no longer start automatically on boot"
        ;;
    test)
        echo "🧪 Test run (foreground mode)..."
        echo "Press Ctrl+C to stop"
        source ../blinkt-env/bin/activate
        python3 bin_led_service.py
        ;;
    clear-errors)
        echo "🧹 Clearing error state..."
        rm -f error_state.json
        echo "🔄 Restarting service..."
        sudo systemctl restart $SERVICE_NAME
        echo "✅ Error state cleared and service restarted"
        ;;
    webui)
        WEBUI_SERVICE="bin-led-webui"
        case "$2" in
            start)
                echo "🚀 Starting $WEBUI_SERVICE service..."
                sudo systemctl start $WEBUI_SERVICE
                sudo systemctl status $WEBUI_SERVICE --no-pager
                ;;
            stop)
                echo "🛑 Stopping $WEBUI_SERVICE service..."
                sudo systemctl stop $WEBUI_SERVICE
                echo "✅ Web UI stopped"
                ;;
            restart)
                echo "🔄 Restarting $WEBUI_SERVICE service..."
                sudo systemctl restart $WEBUI_SERVICE
                sudo systemctl status $WEBUI_SERVICE --no-pager
                ;;
            status)
                sudo systemctl status $WEBUI_SERVICE --no-pager
                ;;
            logs)
                echo "📖 Live web UI logs (Ctrl+C to exit):"
                sudo journalctl -u $WEBUI_SERVICE -f
                ;;
            *)
                echo "Usage: $0 webui {start|stop|restart|status|logs}"
                exit 1
                ;;
        esac
        ;;
    "")
        show_usage
        ;;
    *)
        echo "❌ Unknown command: $1"
        echo ""
        show_usage
        exit 1
        ;;
esac
