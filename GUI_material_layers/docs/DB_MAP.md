# DB Map

This GUI works with two different SQLite roles.

## Working DB

Path: `db/Manufacture_Process_Database.db`

Used for the editable in-GUI process state.

Main tables:

- `Layer`
- `Tool_ALD`
- `Tool_Sputter`
- `Tool_E_beam`
- `Tool_Furnace`
- `Tool_ALD_Material_Gas_Cycle_Relation`
- `Tool_ALD_Cycle`
- `Tool_ALD_Material`
- `Tool_ALD_Gas`
- `Tool_Attachment`

Working-only helper tables:

- `Available_Materials_ALD`
- `Available_Precursors_ALD`
- `Available_Gases_ALD`
- `Available_Materials_Sputter`
- `Available_Gases_Sputter`
- `Available_Materials_E_beam`
- `Available_Materials_Furnace`

## Big Database

Startup target: normally `Memristor_Database.db`

Used for recipe-side persistence.

Main tables touched by this GUI:

- `Recipe`
- `Layer`
- `Tool_ALD`
- `Tool_Sputter`
- `Tool_E_beam`
- `Tool_Furnace`
- `Tool_ALD_Material_Gas_Cycle_Relation`
- `Tool_ALD_Cycle`
- `Tool_ALD_Material`
- `Tool_ALD_Gas`
- `Tool_Attachment`

Context note:

- this GUI uses the recipe/material subtree inside `Memristor_Database.db`
- experiment/device/wafer data may live in the same DB, but this package does not manage those flows
- startup validation checks the selected big DB looks like the main experiment database before continuing, and the picker starts from the Windows Desktop
