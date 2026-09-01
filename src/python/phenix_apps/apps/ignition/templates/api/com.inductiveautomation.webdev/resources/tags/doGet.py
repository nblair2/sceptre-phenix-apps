def doGet(request, session):
	# Read every DNP3 point from the OPC server, keyed by device then item
	# path. Optional ?device= limits the response to one device. Runs
	# gateway-side under jython 2.7 (no f-strings).
	server = "Ignition OPC UA Server"
	wanted = request["params"].get("device")
	result = {}
	devices = system.device.listDevices()
	for row in range(devices.getRowCount()):
		device = str(devices.getValueAt(row, "Name"))
		if wanted and device != wanted:
			continue
		# only real points browse as DATAVARIABLE; skip folder (OBJECT) nodes
		paths = [
			p.getOpcItemPath()
			for p in system.opc.browse(opcServer=server, device=device)
			if str(p.getType()) == "DATAVARIABLE"
		]
		values = system.opc.readValues(server, paths) if paths else []
		result[device] = dict(
			(paths[i], values[i].getValue()) for i in range(len(paths))
		)
	return {"json": result}
