import os

import FreeCADGui as Gui

ICON_DIR = os.path.join(os.path.dirname(__file__), "resources", "icons")


class ProfileBuilderWorkbench(Gui.Workbench):
    MenuText = "Profile Builder"
    ToolTip = "Design and generate standard aluminium T-slot / V-slot extrusion profiles"
    Icon = os.path.join(ICON_DIR, "ProfileBuilder.svg")

    def Initialize(self):
        from . import commands

        groups = commands.register()
        main = ["ProfileBuilder_Create"]
        tools = ["ProfileBuilder_Joints", "ProfileBuilder_RunThrough", "ProfileBuilder_SwapJoint",
                 "ProfileBuilder_Panel",
                 "ProfileBuilder_Brackets", "ProfileBuilder_CalibrateBracket",
                 "Separator", "ProfileBuilder_Pricing",
                 "ProfileBuilder_CutList", "ProfileBuilder_ExportCutList"]
        self.appendToolbar("Profile Builder", main + [group for _key, group, _names in groups])
        self.appendToolbar("Profile Builder tools", tools)
        self.appendMenu("Profiles", main)
        for key, _group, names in groups:
            label = commands.profiles.series_label(key)
            self.appendMenu(["Profiles", label[0].upper() + label[1:]], names)
        self.appendMenu("Profiles", ["Separator"] + tools)

    def Activated(self):
        pass

    def Deactivated(self):
        pass

    def GetClassName(self):
        return "Gui::PythonWorkbench"


Gui.addWorkbench(ProfileBuilderWorkbench())
