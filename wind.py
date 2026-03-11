from kivy.app import App
from kivy.uix.label import Label
from kivy.core.window import Window

Window.set_icon("g.png")
Window.size = (400,300)

class TestApp(App):
    def build(self):
        return Label(text="FENETRE VISIBLE_ii ne\n🐼\n🐵")
if __name__ == "__main__":
    TestApp().run()
