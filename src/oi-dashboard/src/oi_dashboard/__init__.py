"""oi-dashboard — Web dashboard for oi-gateway real-time monitoring."""
from .dashboard import Dashboard, get_dashboard
from .gateway_integration import DashboardIntegration

__all__ = ["Dashboard", "DashboardIntegration", "get_dashboard"]
