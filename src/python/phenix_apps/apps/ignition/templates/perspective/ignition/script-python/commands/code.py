def openPopup(deviceName, index=None):
	params = {"deviceName": deviceName}
	if index is not None:
		params["index"] = index
	system.perspective.openPopup(
		"command",
		"popups/sendCommand",
		params=params,
		title="DNP3 Command - " + deviceName,
		modal=True
	)
