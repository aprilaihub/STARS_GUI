# DB Map

## Database Roles

`GUI_material_layers` works with two SQLite roles.

### Working Database

On the current `main` branch, the running GUI uses an in-memory SQLite database as its working store.

This working store holds the current editor session:

- layer rows
- tool rows
- ALD nested cycle/material/gas rows
- tool attachments
- helper selector values such as available materials, gases, or precursors

This state is not persistent across GUI restarts.

### Main Database

The main database is the selected STARS database, usually `Memristor_Database.db`.

This GUI uses that database for persistent recipe-side storage.

Startup validation checks that the selected file looks like the main experiment database before recipe operations are enabled.

## Working-Side Tables

The working side uses these main tables:

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

Helper tables on the working side:

- `Available_Materials_ALD`
- `Available_Precursors_ALD`
- `Available_Gases_ALD`
- `Available_Materials_Sputter`
- `Available_Gases_Sputter`
- `Available_Materials_E_beam`
- `Available_Materials_Furnace`

## Main-Database Tables Used By This GUI

The persistent recipe side uses these main tables:

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

## Data Ownership

### Owned By The Working Side

- the current editor layout
- unsaved thickness and tool parameter edits
- autosaved session values
- selector helper values learned during editing

### Owned By The Main Database

- saved recipes
- recipe-side tool rows
- recipe-side ALD nested trees
- recipe-side attachments

## Operation Map

### Save Recipe

Copies from:

- working side -> main database

Data copied:

- step ordering and layer placement
- tool parameters
- ALD nested cycle/material/gas rows
- attachments

### Load Recipe

Copies from:

- main database -> working side

Effect:

- clears the current working session
- rebuilds the editor state from the selected recipe

### Replace Recipe

Copies from:

- working side -> existing recipe rows in the main database

Effect:

- keeps the recipe identity
- overwrites its saved contents with the current editor state

## Important Practical Rule

Editing inside the GUI does not directly modify the main database just because autosave is happening.

Autosave only updates the working session.

The main database changes only when a recipe operation explicitly writes to it.
