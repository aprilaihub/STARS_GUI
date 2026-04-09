# DB Map (Quick)

## Working DB (`db/Manufacture_Process_Database.db`)

- Process steps:
  - `Layer`
- Tool parameter tables:
  - `Tool_ALD`
  - `Tool_Sputter`
  - `Tool_E_beam`
  - `Tool_Furnace`
- ALD nested cycle tree:
  - `Tool_ALD_Material_Gas_Cycle_Relation`
  - `Tool_ALD_Cycle`
  - `Tool_ALD_Material`
  - `Tool_ALD_Gas`
- Candidate lists:
  - `Available_Materials_ALD`
  - `Available_Precursors_ALD`
  - `Available_Gases_ALD`
  - `Available_Materials_Sputter`
  - `Available_Gases_Sputter`
  - `Available_Materials_E_beam`
  - `Available_Materials_Furnace`
- Attachments:
  - `Tool_Attachment`
  - each working `Tool_*` row has nullable `attachment_id`

## Recipe DB (`../Database_NEW_V2.db`)

- Recipe headers:
  - `Recipe`
- Recipe process steps:
  - `Layer`
- Recipe tool parameter tables:
  - `Tool_ALD`, `Tool_Sputter`, `Tool_E_beam`, `Tool_Furnace`
- Recipe ALD nested cycle tree:
  - `Tool_ALD_Material_Gas_Cycle_Relation`
  - `Tool_ALD_Cycle`
  - `Tool_ALD_Material`
  - `Tool_ALD_Gas`
- Recipe attachments:
  - `Tool_Attachment`
  - each recipe-side `Tool_*` row has nullable `attachment_id`
- Note:
  - this GUI uses only the recipe-side material subtree in `Database_NEW_V2.db`
  - `Wafer` / `Die` stay in the same DB but are not managed by the GUI recipe flow
