from kivy.app import App
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.graphics import Color, Rectangle
from kivy.core.window import Window

# Configuration de la fenêtre pour ressembler à un écran d'ordi
Window.size = (1000, 700)

class MacOSLauncher(FloatLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        
        # 1. Fond d'écran (Wallpaper)
        with self.canvas.before:
            Color(0.2, 0.4, 0.6, 1) # Un bleu "macOS" par défaut
            self.rect = Rectangle(size=Window.size, pos=self.pos)
        
        # 2. Barre de menus supérieure
        self.top_bar = BoxLayout(
            size_hint=(1, 0.04),
            pos_hint={'top': 1},
            padding=[10, 0]
        )
        with self.top_bar.canvas.before:
            Color(1, 1, 1, 0.2)
            self.top_rect = Rectangle(size=self.top_bar.size, pos=self.top_bar.pos)
            
        self.top_bar.add_widget(Button(text="", size_hint_x=0.05, background_color=(0,0,0,0)))
        self.top_bar.add_widget(Button(text="Fichier", size_hint_x=0.1, background_color=(0,0,0,0)))
        self.add_widget(self.top_bar)

        # 3. Le Dock (Barre d'applications)
        self.dock = BoxLayout(
            size_hint=(0.6, 0.1),
            pos_hint={'center_x': 0.5, 'y': 0.02},
            spacing=10,
            padding=[10, 10]
        )
        with self.dock.canvas.before:
            Color(1, 1, 1, 0.3)
            self.dock_rect = Rectangle(size=self.dock.size, pos=self.dock.pos, radius=[15])
            
        # Ajout de quelques icônes factices
        apps = ["Finder", "Safari", "Mail", "Code", "Music"]
        for app_name in apps:
            btn = Button(text=app_name, background_normal='', background_color=(0.5, 0.5, 0.5, 1))
            self.dock.add_widget(btn)
            
        self.add_widget(self.dock)

class MacKivyApp(App):
    def build(self):
        return MacOSLauncher()

if __name__ == '__main__':
    MacKivyApp().run()