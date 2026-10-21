-- stock now comes from the seller API, the 33 cities were only there to match Evirma's stock.
-- Every WB account switches to the "7 regions" preset of the settings page, Moscow first
UPDATE Parameter
SET value = '[-1257786, -1187265, 12358058, -2133462, -5803327, -364763, -1785058]'
WHERE name LIKE 'wb\_dests:%' ESCAPE '\'
