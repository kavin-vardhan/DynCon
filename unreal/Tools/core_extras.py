"""Two bits of base-game content the Player's side needs, in one place (brief 016).

Editor Python. Imported and called by both `import_content.py` (the full content pipeline,
which owns `/Game/DCCore/`) and `make_maps.py` (the map build, which is what gets re-run when
only this changes), so there is exactly one definition of each and either entry point produces
them.

1. **The screen image set** - `art/samples/screens/screen_1..N.png` into
   `/Game/DCCore/Screens/T_DC_Screen_<n>`. A content pack never carries a screen image: the
   image is a runtime input on `M_Screen`, exactly like the brand colour and the emblem, and
   `UDCSubsystem::GetScreenImage` hands the right one to a piece when it spawns. That is what
   lets "which image the screen is showing" survive a content update: the number survives, and
   the number is all the piece keeps.

2. **The "use" input action** - `/Game/Input/Actions/IA_DCUse`. It has to be Enhanced Input
   and it has to be a real asset: a Shipping build with the Enhanced Input plugin enabled
   processes **no legacy key bindings at all**
   (`UEnhancedPlayerInput::EvaluateInputComponentDelegates` only looks at enhanced input
   components, and debug key bindings are compiled out of Shipping), so there is no code-only
   way to bind a key. `UDCInteractor` loads it by soft path, which is why `/Game/Input` is in
   `DirectoriesToAlwaysCook` - the cook does not follow a soft path.

   The **keys** are not an asset. `FKey`'s `KeyName` is a private UPROPERTY, so the editor's
   Python cannot build one at all (`unreal.Key("E")` is "call() takes at most 0 arguments"),
   and `UInputMappingContext::MapKey` wants one. `UDCInteractor` therefore builds its own
   mapping context at runtime with `EKeys::E` and `EKeys::Gamepad_FaceButton_Bottom` on it -
   which is the better place for them anyway: the keys now sit next to the binding that
   answers them instead of in an asset nobody opens.
"""

import os

import unreal

# The root of this copy of the tree, from this file's own location: unreal/Tools/.
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCREEN_SOURCE = os.path.join(REPO, "art", "samples", "screens")

CORE_SCREENS = "/Game/DCCore/Screens"
INPUT_ROOT = "/Game/Input"
INPUT_ACTIONS = INPUT_ROOT + "/Actions"

USE_ACTION_NAME = "IA_DCUse"

LOG = []


def log(msg):
    line = "[core_extras] %s" % msg
    LOG.append(line)
    unreal.log(line)


def warn(msg):
    line = "[core_extras] WARNING %s" % msg
    LOG.append(line)
    unreal.log_warning(line)


def fail(msg):
    line = "[core_extras] ERROR %s" % msg
    LOG.append(line)
    unreal.log_error(line)


def asset_tools():
    return unreal.AssetToolsHelpers.get_asset_tools()


def load_asset(path):
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        return unreal.EditorAssetLibrary.load_asset(path)
    return None


def safe_set(obj, name, value):
    try:
        obj.set_editor_property(name, value)
        return True
    except Exception as exc:                                    # noqa: BLE001
        warn("could not set %s.%s: %s" % (type(obj).__name__, name, exc))
        return False


def save(asset):
    if asset is None:
        return
    try:
        unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False)
    except Exception as exc:                                    # noqa: BLE001
        warn("could not save %s: %s" % (asset.get_name(), exc))


# --------------------------------------------------------------------------- screen images

def import_screen_set(source_dir=None, reimport=False):
    """Every screen_<n>.png in order, until one is missing. Returns the asset paths."""
    source = source_dir or SCREEN_SOURCE
    if not os.path.isdir(source):
        warn("no screen image set at %s - run art\\tools\\make_screen_set.py "
             "(every screen then keeps the image its pack was built with)" % source)
        return []

    unreal.EditorAssetLibrary.make_directory(CORE_SCREENS)
    made = []
    index = 1
    while True:
        png = os.path.join(source, "screen_%d.png" % index)
        if not os.path.isfile(png):
            break
        name = "T_DC_Screen_%d" % index
        path = "%s/%s" % (CORE_SCREENS, name)
        tex = load_asset(path)
        if tex is None or reimport:
            task = unreal.AssetImportTask()
            task.set_editor_property("filename", png)
            task.set_editor_property("destination_path", CORE_SCREENS)
            task.set_editor_property("destination_name", name)
            task.set_editor_property("automated", True)
            task.set_editor_property("replace_existing", True)
            task.set_editor_property("save", False)
            # Naming the factory keeps the import on the classic path; Interchange (the 5.5+
            # default) calls into the content browser when it finishes, which asserts in a
            # commandlet with no Slate application.
            task.set_editor_property("factory", unreal.TextureFactory())
            asset_tools().import_asset_tasks([task])
            tex = load_asset(path)
        if tex is None:
            fail("screen image import failed: %s" % png)
            index += 1
            continue
        safe_set(tex, "compression_settings", unreal.TextureCompressionSettings.TC_DEFAULT)
        safe_set(tex, "srgb", True)
        # Clamp, not wrap: the screen quad's UVs run 0..1 and a wrapped edge would put a
        # sliver of the opposite side of the picture down the frame.
        safe_set(tex, "address_x", unreal.TextureAddress.TA_CLAMP)
        safe_set(tex, "address_y", unreal.TextureAddress.TA_CLAMP)
        save(tex)
        made.append(path)
        index += 1

    log("screen image set: %d image(s) -> %s" % (len(made), CORE_SCREENS))
    return made


# --------------------------------------------------------------------------- the use input

def make_input_assets():
    """IA_DCUse. The keys that trigger it are UDCInteractor's, not an asset's."""
    unreal.EditorAssetLibrary.make_directory(INPUT_ACTIONS)

    action_path = "%s/%s" % (INPUT_ACTIONS, USE_ACTION_NAME)
    action = load_asset(action_path)
    if action is None:
        try:
            factory = unreal.InputAction_Factory()
        except AttributeError:
            fail("unreal.InputAction_Factory is not in this editor - is the EnhancedInput "
                 "plugin enabled?")
            return {}
        action = asset_tools().create_asset(USE_ACTION_NAME, INPUT_ACTIONS,
                                            unreal.InputAction, factory)
    if action is None:
        fail("could not create %s" % action_path)
        return {}
    # A plain press: no axis, no value. ETriggerEvent::Started is what UDCInteractor binds.
    safe_set(action, "value_type", unreal.InputActionValueType.BOOLEAN)
    save(action)

    log("use input: %s (the keys are built in UDCInteractor::BindInput)" % USE_ACTION_NAME)
    return {"action": action_path}


def build_all(reimport=False):
    return {"screens": import_screen_set(reimport=reimport),
            "input": make_input_assets()}
