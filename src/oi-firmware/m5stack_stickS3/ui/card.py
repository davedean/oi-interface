"""
Card display for M5Stack StickS3.

This module provides card/message display functionality showing
title, body text, and interactive options (buttons).
"""

from .display import WHITE, BLACK, GRAY, DARK_GRAY


class CardDisplay:
    """
    Card display showing title, body text, and options.
    
    Displays message cards with up to 2 options (e.g., Yes/No buttons).
    """
    
    def __init__(self, renderer, width: int = 135, height: int = 240):
        """
        Initialize card display.
        
        Args:
            renderer: Renderer instance
            width: Display width
            height: Display height
        """
        self._renderer = renderer
        self._width = width
        self._height = height
        
        # Current card state
        self._title = ""
        self._body = ""
        self._options = []  # [{"id": "yes", "label": "Yes"}, ...]
        
        # Button positions
        self._button_y = self._height - 40
        self._button_width = 50
        self._button_height = 24
    
    def show_card(self, title: str, body: str = "", options: list = None):
        """
        Show a card on the display.
        
        Args:
            title: Card title
            body: Body text (optional)
            options: List of options [{"id": "id", "label": "Label"}, ...]
        """
        self._title = title
        self._body = body
        self._options = options or []
        
        self._render()
    
    def _render(self):
        """Render the current card."""
        # Clear screen
        self._renderer.clear()
        
        # Draw card background
        self._renderer.rect(5, 5, self._width - 10, self._height - 50, GRAY, fill=True)
        
        # Draw title
        title_y = 15
        self._wrap_text(self._title, 10, title_y, self._width - 20, WHITE)
        
        # Draw body text
        body_y = title_y + 30
        if self._body:
            self._wrap_text(self._body, 10, body_y, self._width - 20, WHITE, max_lines=4)
        
        # Draw options as buttons
        if self._options:
            self._render_options()
        else:
            # No options - show "Press to respond" hint
            hint_y = self._height - 20
            self._renderer.text_centered(hint_y, "Press button", GRAY)
    
    def _wrap_text(self, text: str, x: int, y: int, max_width: int, 
                   color: int, max_lines: int = 10) -> int:
        """
        Draw wrapped text.
        
        Returns:
            Y position after text
        """
        # Simple word wrap
        words = text.split()
        lines = []
        current_line = ""
        
        for word in words:
            test_line = current_line + " " + word if current_line else word
            if len(test_line) * 6 <= max_width:  # 6 pixels per character
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        
        if current_line:
            lines.append(current_line)
        
        # Draw lines
        line_height = 12
        for i, line in enumerate(lines[:max_lines]):
            self._renderer.text(x, y + i * line_height, line, color)
        
        return y + len(lines) * line_height
    
    def _render_options(self):
        """Render option buttons."""
        num_options = len(self._options)
        
        if num_options == 1:
            # Single button - center
            btn_x = (self._width - self._button_width) // 2
            self._draw_button(btn_x, self._button_y, self._button_width,
                            self._button_height, self._options[0]["label"])
        
        elif num_options == 2:
            # Two buttons - side by side
            gap = 10
            total_width = self._button_width * 2 + gap
            start_x = (self._width - total_width) // 2
            
            self._draw_button(start_x, self._button_y, self._button_width,
                            self._button_height, self._options[0]["label"])
            self._draw_button(start_x + self._button_width + gap, self._button_y,
                            self._button_width, self._button_height, self._options[1]["label"])
    
    def _draw_button(self, x: int, y: int, w: int, h: int, label: str):
        """Draw a button."""
        # Button background
        self._renderer.rect(x, y, w, h, DARK_GRAY, fill=True)
        
        # Button border
        self._renderer.rect(x, y, w, h, WHITE, fill=False)
        
        # Button label
        label_x = x + (w - len(label) * 6) // 2
        label_y = y + (h - 8) // 2
        self._renderer.text(label_x, label_y, label, WHITE)
    
    def handle_button_press(self, button_id: str) -> str:
        """
        Handle a button press.
        
        Args:
            button_id: Button identifier ("a" or "b")
        
        Returns:
            Option ID if button matches an option, None otherwise.
        """
        if not self._options:
            return None
        
        # Map physical buttons to options
        num_options = len(self._options)
        
        if num_options == 1:
            # Any button triggers the single option
            return self._options[0]["id"]
        
        elif num_options == 2:
            # Button A = option 0, Button B = option 1
            if button_id == "a":
                return self._options[0]["id"]
            elif button_id == "b":
                return self._options[1]["id"]
        
        return None
    
    def clear(self):
        """Clear the card display."""
        self._title = ""
        self._body = ""
        self._options = []
        self._renderer.clear()


class ConfirmDialog:
    """
    Simple confirmation dialog (Yes/No).
    """
    
    def __init__(self, card_display: CardDisplay):
        """Initialize with card display."""
        self._card = card_display
    
    def show(self, title: str, on_confirm=None, on_cancel=None):
        """
        Show a confirmation dialog.
        
        Args:
            title: Confirmation message
            on_confirm: Callback for Yes
            on_cancel: Callback for No
        """
        self._card.show_card(title, "", [
            {"id": "yes", "label": "Yes"},
            {"id": "no", "label": "No"}
        ])
        
        # Store callbacks
        self._on_confirm = on_confirm
        self._on_cancel = on_cancel
    
    def handle_response(self, response_id: str):
        """Handle the user's response."""
        if response_id == "yes" and self._on_confirm:
            self._on_confirm()
        elif response_id == "no" and self._on_cancel:
            self._on_cancel()


def create_card_display(renderer, width: int = 135, height: int = 240) -> CardDisplay:
    """Factory function to create a card display."""
    return CardDisplay(renderer, width, height)