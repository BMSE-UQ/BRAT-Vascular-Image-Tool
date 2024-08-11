import customtkinter as ctk


class MyScrollableCheckboxFrame(ctk.CTkScrollableFrame):
    def __init__(self, master, title, values):
        super().__init__(master, label_text=title)
        self.grid_columnconfigure(0, weight=1)
        self.values = values
        self.checkboxes = []

        for i, value in enumerate(self.values):
            checkbox = ctk.CTkCheckBox(self, text=value)
            checkbox.grid(row=i, column=0, padx=10, pady=(10, 0), sticky="w")
            self.checkboxes.append(checkbox)

    def get(self):
        checked_checkboxes = []
        for checkbox in self.checkboxes:
            if checkbox.get() == 1:
                checked_checkboxes.append(checkbox.cget("text"))
        return checked_checkboxes


class App(ctk.CTk):
    def __init__(self):
        #Initiate super
        super().__init__()
            
        #Create Grid
        self.title("BRAT -  Vascular Image Analysis")
        self.geometry(f"{1100}x{580}")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=2)

        #Textbox Name
        self.nameTag = ctk.CTkTextbox(self,state = "disabled")
        self.nameTag.insert("0.0", "BRAT")
        self.nameTag.grid(row = 0, column=0, sticky = "nsw")

        #Scrollable Checkbox Frame
        values = ["value 1", "value 2", "value 3", "value 4", "value 5", "value 6"]
        self.scrollable_checkboxFrame = MyScrollableCheckboxFrame(self, title = "User Settings", values =values)
        self.scrollable_checkboxFrame.grid(row = 0, column = 1, pady = 10, sticky = "nsew", columnspan = 2)

if __name__ == '__main__':
    app = App()
    app.mainloop()
