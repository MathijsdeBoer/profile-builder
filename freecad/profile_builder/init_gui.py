import os

import FreeCAD as App
import FreeCADGui as Gui

QT_TRANSLATE_NOOP = App.Qt.QT_TRANSLATE_NOOP

ICON_DIR = os.path.join(os.path.dirname(__file__), "resources", "icons")

# Compiled translations (ProfileBuilder_<language>.qm); see tools/update_translations.py.
Gui.addLanguagePath(os.path.join(os.path.dirname(__file__), "resources", "translations"))
Gui.updateLocale()


class ProfileBuilderWorkbench(Gui.Workbench):
    # FreeCAD shows these as they are, so translate them here (the locale is loaded above).
    MenuText = App.Qt.translate("Workbench", "Profile Builder")
    ToolTip = App.Qt.translate("Workbench", "Design and generate standard aluminium T-slot / V-slot extrusion profiles")
    Icon = os.path.join(ICON_DIR, "ProfileBuilder.svg")

    def Initialize(self):
        from . import commands

        groups = commands.register()
        main = ["ProfileBuilder_Create", "ProfileBuilder_BoxFrame"]
        joints_tools = ["ProfileBuilder_Joints", "ProfileBuilder_AlignSlots",
                        "ProfileBuilder_RunThrough", "ProfileBuilder_SwapJoint"]
        component_tools = ["ProfileBuilder_Panel", "ProfileBuilder_Carriage",
                           "ProfileBuilder_Brackets", "ProfileBuilder_EndPlates", "ProfileBuilder_CalibrateBracket"]
        output_tools = ["ProfileBuilder_Pricing",
                        "ProfileBuilder_CutList", "ProfileBuilder_ExportCutList", "ProfileBuilder_ExportPanels",
                        "ProfileBuilder_ShowMarks", "Separator",
                        "ProfileBuilder_CheckFrame", "ProfileBuilder_FrameStiffness"]
        self.appendToolbar(QT_TRANSLATE_NOOP("Workbench", "Profile Builder"),
                           main + [group for _key, group, _names in groups])
        self.appendToolbar(QT_TRANSLATE_NOOP("Workbench", "Joints and Alignment"), joints_tools)
        self.appendToolbar(QT_TRANSLATE_NOOP("Workbench", "Component Tools"), component_tools)
        self.appendToolbar(QT_TRANSLATE_NOOP("Workbench", "Output and Analysis"), output_tools)
        menu = QT_TRANSLATE_NOOP("Workbench", "Profiles")
        self.appendMenu(menu, main)
        for key, _group, names in groups:
            label = commands.profiles.series_label(key)
            self.appendMenu([menu, label[0].upper() + label[1:]], names)
        self.appendMenu(menu, ["Separator"] + joints_tools + component_tools +
                        ["Separator"] + output_tools + ["ProfileBuilder_RenumberMarks"])

    def Activated(self):
        from . import context_tasks
        Gui.Control.addTaskWatcher(context_tasks.watchers())

    def Deactivated(self):
        Gui.Control.clearTaskWatcher()

    def GetClassName(self):
        return "Gui::PythonWorkbench"


Gui.addWorkbench(ProfileBuilderWorkbench())
