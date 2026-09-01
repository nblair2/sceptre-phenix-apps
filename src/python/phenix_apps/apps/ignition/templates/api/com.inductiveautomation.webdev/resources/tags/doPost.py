def doPost(request, session):
    data = request['postData']
    deviceName = data.get('deviceName', 'DNP3')
    index      = int(data['index'])
    tcc        = int(data.get('tcc', 1))      # 0=NUL, 1=CLOSE, 2=TRIP
    opType     = int(data.get('opType', 3))   # 0=NUL, 1=PULSE_ON, 2=PULSE_OFF, 3=LATCH_ON, 4=LATCH_OFF
    count      = int(data.get('count', 1))
    onTime     = int(data.get('onTime', 1000))
    offTime    = int(data.get('offTime', 1000))

    try:
        system.dnp.directOperateBinary(deviceName, index, tcc, opType, count, onTime, offTime)
        result = {'status': 'ok', 'device': deviceName, 'index': index}
    except Exception as e:
        result = {'status': 'error', 'message': str(e)}

    return {'json': result}