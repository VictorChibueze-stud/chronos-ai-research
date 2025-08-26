# Second attempt: build the full series cleanly, then compute fractal & zigzag pivots,
# HH/HL/LH/LL labels, BOS and CHOCH. We'll also save CSV/JSON outputs.
import pandas as pd
import numpy as np
from typing import List, Tuple, Dict, Optional


data = {"series": [
  {"datetime":"2025-07-30T00:00:00+00:00","date":"2025-07-30","epoch":1753833600,"open":6284.031,"high":6287.926,"low":6265.287,"close":6278.341},
  {"datetime":"2025-07-30T04:00:00+00:00","date":"2025-07-30","epoch":1753848000,"open":6278.461,"high":6303.371,"low":6278.337,"close":6299.114},
  {"datetime":"2025-07-30T08:00:00+00:00","date":"2025-07-30","epoch":1753862400,"open":6299.434,"high":6309.276,"low":6292.559,"close":6305.735},
  {"datetime":"2025-07-30T12:00:00+00:00","date":"2025-07-30","epoch":1753876800,"open":6305.875,"high":6317.597,"low":6300.794,"close":6304.93},
  {"datetime":"2025-07-30T16:00:00+00:00","date":"2025-07-30","epoch":1753891200,"open":6304.88,"high":6313.851,"low":6297.858,"close":6312.695},
  {"datetime":"2025-07-30T20:00:00+00:00","date":"2025-07-30","epoch":1753905600,"open":6312.833,"high":6321.152,"low":6303.562,"close":6309.086},
  {"datetime":"2025-07-31T00:00:00+00:00","date":"2025-07-31","epoch":1753920000,"open":6309.074,"high":6325.523,"low":6307.839,"close":6311.881},
  {"datetime":"2025-07-31T04:00:00+00:00","date":"2025-07-31","epoch":1753934400,"open":6312.193,"high":6314.09,"low":6279.194,"close":6279.636},
  {"datetime":"2025-07-31T08:00:00+00:00","date":"2025-07-31","epoch":1753948800,"open":6279.841,"high":6285.85,"low":6271.389,"close":6277.613},
  {"datetime":"2025-07-31T12:00:00+00:00","date":"2025-07-31","epoch":1753963200,"open":6277.501,"high":6279.14,"low":6247.289,"close":6249.331},
  {"datetime":"2025-07-31T16:00:00+00:00","date":"2025-07-31","epoch":1753977600,"open":6249.377,"high":6252.517,"low":6228.481,"close":6232.32},
  {"datetime":"2025-07-31T20:00:00+00:00","date":"2025-07-31","epoch":1753992000,"open":6232.321,"high":6254.257,"low":6225.34,"close":6244.702},
  {"datetime":"2025-08-01T00:00:00+00:00","date":"2025-08-01","epoch":1754006400,"open":6244.698,"high":6257.029,"low":6238.837,"close":6251.726},
  {"datetime":"2025-08-01T04:00:00+00:00","date":"2025-08-01","epoch":1754020800,"open":6251.754,"high":6264.22,"low":6249.269,"close":6254.551},
  {"datetime":"2025-08-01T08:00:00+00:00","date":"2025-08-01","epoch":1754035200,"open":6254.85,"high":6266.017,"low":6254.078,"close":6261.481},
  {"datetime":"2025-08-01T12:00:00+00:00","date":"2025-08-01","epoch":1754049600,"open":6261.613,"high":6271.45,"low":6254.137,"close":6266.808},
  {"datetime":"2025-08-01T16:00:00+00:00","date":"2025-08-01","epoch":1754064000,"open":6266.656,"high":6283.667,"low":6263.84,"close":6283.546},
  {"datetime":"2025-08-01T20:00:00+00:00","date":"2025-08-01","epoch":1754078400,"open":6283.69,"high":6306.887,"low":6283.315,"close":6292.494},
  {"datetime":"2025-08-02T00:00:00+00:00","date":"2025-08-02","epoch":1754092800,"open":6292.594,"high":6297.615,"low":6272.021,"close":6282.62},
  {"datetime":"2025-08-02T04:00:00+00:00","date":"2025-08-02","epoch":1754107200,"open":6282.61,"high":6283.427,"low":6267.193,"close":6268.548},
  {"datetime":"2025-08-02T08:00:00+00:00","date":"2025-08-02","epoch":1754121600,"open":6268.672,"high":6274.428,"low":6223.475,"close":6226.123},
  {"datetime":"2025-08-02T12:00:00+00:00","date":"2025-08-02","epoch":1754136000,"open":6225.98,"high":6255.968,"low":6225.593,"close":6255.446},
  {"datetime":"2025-08-02T16:00:00+00:00","date":"2025-08-02","epoch":1754150400,"open":6255.616,"high":6265.004,"low":6253.774,"close":6258.574},
  {"datetime":"2025-08-02T20:00:00+00:00","date":"2025-08-02","epoch":1754164800,"open":6258.878,"high":6259.615,"low":6243.583,"close":6246.28},
  {"datetime":"2025-08-03T00:00:00+00:00","date":"2025-08-03","epoch":1754179200,"open":6246.256,"high":6247.849,"low":6230.102,"close":6242.086},
  {"datetime":"2025-08-03T04:00:00+00:00","date":"2025-08-03","epoch":1754193600,"open":6242.133,"high":6258.075,"low":6240.0,"close":6253.159},
  {"datetime":"2025-08-03T08:00:00+00:00","date":"2025-08-03","epoch":1754208000,"open":6253.155,"high":6255.837,"low":6222.246,"close":6224.898},
  {"datetime":"2025-08-03T12:00:00+00:00","date":"2025-08-03","epoch":1754222400,"open":6224.89,"high":6225.434,"low":6203.936,"close":6214.233},
  {"datetime":"2025-08-03T16:00:00+00:00","date":"2025-08-03","epoch":1754236800,"open":6214.362,"high":6216.415,"low":6202.839,"close":6208.091},
  {"datetime":"2025-08-03T20:00:00+00:00","date":"2025-08-03","epoch":1754251200,"open":6208.226,"high":6216.25,"low":6201.577,"close":6214.075},
  {"datetime":"2025-08-04T00:00:00+00:00","date":"2025-08-04","epoch":1754265600,"open":6213.949,"high":6213.984,"low":6198.148,"close":6203.342},
  {"datetime":"2025-08-04T04:00:00+00:00","date":"2025-08-04","epoch":1754280000,"open":6203.409,"high":6210.16,"low":6188.067,"close":6194.035},
  {"datetime":"2025-08-04T08:00:00+00:00","date":"2025-08-04","epoch":1754294400,"open":6194.079,"high":6206.55,"low":6190.28,"close":6203.275},
  {"datetime":"2025-08-04T12:00:00+00:00","date":"2025-08-04","epoch":1754308800,"open":6202.955,"high":6211.559,"low":6193.049,"close":6195.374},
  {"datetime":"2025-08-04T16:00:00+00:00","date":"2025-08-04","epoch":1754323200,"open":6195.6,"high":6212.867,"low":6189.068,"close":6206.313},
  {"datetime":"2025-08-04T20:00:00+00:00","date":"2025-08-04","epoch":1754337600,"open":6206.253,"high":6206.73,"low":6175.634,"close":6183.122},
  {"datetime":"2025-08-05T00:00:00+00:00","date":"2025-08-05","epoch":1754352000,"open":6183.085,"high":6199.235,"low":6177.329,"close":6198.995},
  {"datetime":"2025-08-05T04:00:00+00:00","date":"2025-08-05","epoch":1754366400,"open":6198.766,"high":6199.314,"low":6180.701,"close":6181.968},
  {"datetime":"2025-08-05T08:00:00+00:00","date":"2025-08-05","epoch":1754380800,"open":6181.964,"high":6190.0,"low":6170.395,"close":6175.329},
  {"datetime":"2025-08-05T12:00:00+00:00","date":"2025-08-05","epoch":1754395200,"open":6175.253,"high":6186.139,"low":6173.957,"close":6180.594},
  {"datetime":"2025-08-05T16:00:00+00:00","date":"2025-08-05","epoch":1754409600,"open":6180.344,"high":6182.925,"low":6168.131,"close":6173.719},
  {"datetime":"2025-08-05T20:00:00+00:00","date":"2025-08-05","epoch":1754424000,"open":6173.665,"high":6174.698,"low":6152.665,"close":6158.442},
  {"datetime":"2025-08-06T00:00:00+00:00","date":"2025-08-06","epoch":1754438400,"open":6158.129,"high":6166.776,"low":6151.442,"close":6159.759},
  {"datetime":"2025-08-06T04:00:00+00:00","date":"2025-08-06","epoch":1754452800,"open":6159.84,"high":6178.545,"low":6157.452,"close":6176.613},
  {"datetime":"2025-08-06T08:00:00+00:00","date":"2025-08-06","epoch":1754467200,"open":6176.429,"high":6183.824,"low":6154.677,"close":6155.317},
  {"datetime":"2025-08-06T12:00:00+00:00","date":"2025-08-06","epoch":1754481600,"open":6155.292,"high":6156.471,"low":6135.995,"close":6141.513},
  {"datetime":"2025-08-06T16:00:00+00:00","date":"2025-08-06","epoch":1754496000,"open":6141.757,"high":6148.618,"low":6122.572,"close":6123.892},
  {"datetime":"2025-08-06T20:00:00+00:00","date":"2025-08-06","epoch":1754510400,"open":6123.893,"high":6126.335,"low":6106.017,"close":6109.786},
  {"datetime":"2025-08-07T00:00:00+00:00","date":"2025-08-07","epoch":1754524800,"open":6109.693,"high":6134.558,"low":6109.693,"close":6126.183},
  {"datetime":"2025-08-07T04:00:00+00:00","date":"2025-08-07","epoch":1754539200,"open":6126.159,"high":6141.295,"low":6123.842,"close":6139.458},
  {"datetime":"2025-08-07T08:00:00+00:00","date":"2025-08-07","epoch":1754553600,"open":6139.311,"high":6154.178,"low":6132.701,"close":6147.047},
  {"datetime":"2025-08-07T12:00:00+00:00","date":"2025-08-07","epoch":1754568000,"open":6147.165,"high":6152.82,"low":6127.744,"close":6134.27},
  {"datetime":"2025-08-07T16:00:00+00:00","date":"2025-08-07","epoch":1754582400,"open":6134.418,"high":6138.618,"low":6119.869,"close":6124.839},
  {"datetime":"2025-08-07T20:00:00+00:00","date":"2025-08-07","epoch":1754596800,"open":6125.103,"high":6140.061,"low":6120.904,"close":6136.534},
  {"datetime":"2025-08-08T00:00:00+00:00","date":"2025-08-08","epoch":1754611200,"open":6136.802,"high":6139.025,"low":6115.875,"close":6119.328},
  {"datetime":"2025-08-08T04:00:00+00:00","date":"2025-08-08","epoch":1754625600,"open":6119.325,"high":6131.31,"low":6113.916,"close":6119.0},
  {"datetime":"2025-08-08T08:00:00+00:00","date":"2025-08-08","epoch":1754640000,"open":6118.7,"high":6148.313,"low":6117.534,"close":6147.552},
  {"datetime":"2025-08-08T12:00:00+00:00","date":"2025-08-08","epoch":1754654400,"open":6147.641,"high":6158.346,"low":6143.419,"close":6149.67},
  {"datetime":"2025-08-08T16:00:00+00:00","date":"2025-08-08","epoch":1754668800,"open":6149.671,"high":6179.143,"low":6148.175,"close":6168.588},
  {"datetime":"2025-08-08T20:00:00+00:00","date":"2025-08-08","epoch":1754683200,"open":6168.407,"high":6183.052,"low":6166.139,"close":6181.866},
  {"datetime":"2025-08-09T00:00:00+00:00","date":"2025-08-09","epoch":1754697600,"open":6181.724,"high":6186.314,"low":6170.393,"close":6178.588},
  {"datetime":"2025-08-09T04:00:00+00:00","date":"2025-08-09","epoch":1754712000,"open":6178.761,"high":6197.593,"low":6175.691,"close":6179.933},
  {"datetime":"2025-08-09T08:00:00+00:00","date":"2025-08-09","epoch":1754726400,"open":6180.078,"high":6180.557,"low":6163.256,"close":6168.879},
  {"datetime":"2025-08-09T12:00:00+00:00","date":"2025-08-09","epoch":1754740800,"open":6168.659,"high":6173.705,"low":6147.907,"close":6150.659},
  {"datetime":"2025-08-09T16:00:00+00:00","date":"2025-08-09","epoch":1754755200,"open":6150.633,"high":6173.533,"low":6146.877,"close":6173.282},
  {"datetime":"2025-08-09T20:00:00+00:00","date":"2025-08-09","epoch":1754769600,"open":6173.055,"high":6188.294,"low":6156.789,"close":6185.854},
  {"datetime":"2025-08-10T00:00:00+00:00","date":"2025-08-10","epoch":1754784000,"open":6185.93,"high":6190.376,"low":6166.904,"close":6175.859},
  {"datetime":"2025-08-10T04:00:00+00:00","date":"2025-08-10","epoch":1754798400,"open":6176.069,"high":6192.302,"low":6170.611,"close":6190.508},
  {"datetime":"2025-08-10T08:00:00+00:00","date":"2025-08-10","epoch":1754812800,"open":6190.705,"high":6204.694,"low":6185.606,"close":6188.204},
  {"datetime":"2025-08-10T12:00:00+00:00","date":"2025-08-10","epoch":1754827200,"open":6188.287,"high":6193.199,"low":6170.293,"close":6170.46},
  {"datetime":"2025-08-10T16:00:00+00:00","date":"2025-08-10","epoch":1754841600,"open":6170.27,"high":6188.734,"low":6166.206,"close":6186.843},
  {"datetime":"2025-08-10T20:00:00+00:00","date":"2025-08-10","epoch":1754856000,"open":6186.64,"high":6188.84,"low":6173.443,"close":6180.905},
  {"datetime":"2025-08-11T00:00:00+00:00","date":"2025-08-11","epoch":1754870400,"open":6180.863,"high":6188.541,"low":6172.074,"close":6173.54},
  {"datetime":"2025-08-11T04:00:00+00:00","date":"2025-08-11","epoch":1754884800,"open":6173.366,"high":6175.413,"low":6146.95,"close":6160.51},
  {"datetime":"2025-08-11T08:00:00+00:00","date":"2025-08-11","epoch":1754899200,"open":6160.676,"high":6176.205,"low":6159.41,"close":6166.415},
  {"datetime":"2025-08-11T12:00:00+00:00","date":"2025-08-11","epoch":1754913600,"open":6166.445,"high":6191.68,"low":6165.746,"close":6187.246},
  {"datetime":"2025-08-11T16:00:00+00:00","date":"2025-08-11","epoch":1754928000,"open":6187.422,"high":6189.93,"low":6167.417,"close":6167.727},
  {"datetime":"2025-08-11T20:00:00+00:00","date":"2025-08-11","epoch":1754942400,"open":6167.715,"high":6174.132,"low":6160.376,"close":6169.796},
  {"datetime":"2025-08-12T00:00:00+00:00","date":"2025-08-12","epoch":1754956800,"open":6169.801,"high":6174.043,"low":6148.223,"close":6151.194},
  {"datetime":"2025-08-12T04:00:00+00:00","date":"2025-08-12","epoch":1754971200,"open":6151.137,"high":6152.475,"low":6124.613,"close":6124.768},
  {"datetime":"2025-08-12T08:00:00+00:00","date":"2025-08-12","epoch":1754985600,"open":6124.781,"high":6126.373,"low":6112.059,"close":6123.454},
  {"datetime":"2025-08-12T12:00:00+00:00","date":"2025-08-12","epoch":1755000000,"open":6123.534,"high":6123.846,"low":6107.874,"close":6117.157},
  {"datetime":"2025-08-12T16:00:00+00:00","date":"2025-08-12","epoch":1755014400,"open":6117.425,"high":6118.098,"low":6098.312,"close":6107.332},
  {"datetime":"2025-08-12T20:00:00+00:00","date":"2025-08-12","epoch":1755028800,"open":6107.152,"high":6108.756,"low":6085.68,"close":6091.094},
  {"datetime":"2025-08-13T00:00:00+00:00","date":"2025-08-13","epoch":1755043200,"open":6091.177,"high":6100.059,"low":6079.169,"close":6082.074},
  {"datetime":"2025-08-13T04:00:00+00:00","date":"2025-08-13","epoch":1755057600,"open":6081.997,"high":6082.617,"low":6054.472,"close":6054.594},
  {"datetime":"2025-08-13T08:00:00+00:00","date":"2025-08-13","epoch":1755072000,"open":6054.256,"high":6076.086,"low":6052.286,"close":6064.239},
  {"datetime":"2025-08-13T12:00:00+00:00","date":"2025-08-13","epoch":1755086400,"open":6064.407,"high":6081.559,"low":6060.193,"close":6066.204},
  {"datetime":"2025-08-13T16:00:00+00:00","date":"2025-08-13","epoch":1755100800,"open":6066.165,"high":6072.307,"low":6049.358,"close":6058.549},
  {"datetime":"2025-08-13T20:00:00+00:00","date":"2025-08-13","epoch":1755115200,"open":6058.466,"high":6069.78,"low":6053.971,"close":6061.622},
  {"datetime":"2025-08-14T00:00:00+00:00","date":"2025-08-14","epoch":1755129600,"open":6061.595,"high":6081.122,"low":6055.98,"close":6080.543},
  {"datetime":"2025-08-14T04:00:00+00:00","date":"2025-08-14","epoch":1755144000,"open":6080.402,"high":6089.316,"low":6078.001,"close":6079.361},
  {"datetime":"2025-08-14T08:00:00+00:00","date":"2025-08-14","epoch":1755158400,"open":6079.538,"high":6092.252,"low":6074.558,"close":6085.993},
  {"datetime":"2025-08-14T12:00:00+00:00","date":"2025-08-14","epoch":1755172800,"open":6085.952,"high":6103.929,"low":6085.952,"close":6101.174},
  {"datetime":"2025-08-14T16:00:00+00:00","date":"2025-08-14","epoch":1755187200,"open":6101.325,"high":6112.7,"low":6098.174,"close":6108.156},
  {"datetime":"2025-08-14T20:00:00+00:00","date":"2025-08-14","epoch":1755201600,"open":6108.459,"high":6108.459,"low":6082.867,"close":6084.758},
  {"datetime":"2025-08-15T00:00:00+00:00","date":"2025-08-15","epoch":1755216000,"open":6084.689,"high":6092.703,"low":6077.101,"close":6089.561},
  {"datetime":"2025-08-15T04:00:00+00:00","date":"2025-08-15","epoch":1755230400,"open":6089.693,"high":6091.159,"low":6079.799,"close":6090.992},
  {"datetime":"2025-08-15T08:00:00+00:00","date":"2025-08-15","epoch":1755244800,"open":6091.202,"high":6098.411,"low":6074.424,"close":6077.614},
  {"datetime":"2025-08-15T12:00:00+00:00","date":"2025-08-15","epoch":1755259200,"open":6077.632,"high":6089.412,"low":6068.788,"close":6068.788},
  {"datetime":"2025-08-15T16:00:00+00:00","date":"2025-08-15","epoch":1755273600,"open":6068.76,"high":6071.611,"low":6052.182,"close":6056.573},
  {"datetime":"2025-08-15T20:00:00+00:00","date":"2025-08-15","epoch":1755288000,"open":6056.597,"high":6069.839,"low":6051.893,"close":6057.949},
  {"datetime":"2025-08-16T00:00:00+00:00","date":"2025-08-16","epoch":1755302400,"open":6058.101,"high":6061.683,"low":6043.669,"close":6049.882},
  {"datetime":"2025-08-16T04:00:00+00:00","date":"2025-08-16","epoch":1755316800,"open":6049.843,"high":6063.957,"low":6033.639,"close":6036.215},
  {"datetime":"2025-08-16T08:00:00+00:00","date":"2025-08-16","epoch":1755331200,"open":6036.134,"high":6050.137,"low":6032.888,"close":6037.219},
  {"datetime":"2025-08-16T12:00:00+00:00","date":"2025-08-16","epoch":1755345600,"open":6037.259,"high":6037.869,"low":6024.698,"close":6028.592},
  {"datetime":"2025-08-16T16:00:00+00:00","date":"2025-08-16","epoch":1755360000,"open":6028.839,"high":6049.741,"low":6024.594,"close":6045.898},
  {"datetime":"2025-08-16T20:00:00+00:00","date":"2025-08-16","epoch":1755374400,"open":6045.908,"high":6064.065,"low":6045.537,"close":6060.617},
  {"datetime":"2025-08-17T00:00:00+00:00","date":"2025-08-17","epoch":1755388800,"open":6060.754,"high":6079.035,"low":6059.911,"close":6072.682},
  {"datetime":"2025-08-17T04:00:00+00:00","date":"2025-08-17","epoch":1755403200,"open":6072.714,"high":6074.938,"low":6058.67,"close":6058.861},
  {"datetime":"2025-08-17T08:00:00+00:00","date":"2025-08-17","epoch":1755417600,"open":6059.082,"high":6060.007,"low":6028.411,"close":6042.177},
  {"datetime":"2025-08-17T12:00:00+00:00","date":"2025-08-17","epoch":1755432000,"open":6041.955,"high":6046.051,"low":6019.89,"close":6020.492},
  {"datetime":"2025-08-17T16:00:00+00:00","date":"2025-08-17","epoch":1755446400,"open":6020.478,"high":6031.83,"low":6012.9,"close":6029.927},
  {"datetime":"2025-08-17T20:00:00+00:00","date":"2025-08-17","epoch":1755460800,"open":6029.938,"high":6032.664,"low":6014.533,"close":6023.138},
  {"datetime":"2025-08-18T00:00:00+00:00","date":"2025-08-18","epoch":1755475200,"open":6022.969,"high":6029.068,"low":6012.944,"close":6025.371},
  {"datetime":"2025-08-18T04:00:00+00:00","date":"2025-08-18","epoch":1755489600,"open":6025.447,"high":6039.468,"low":6025.277,"close":6028.74},
  {"datetime":"2025-08-18T08:00:00+00:00","date":"2025-08-18","epoch":1755504000,"open":6028.598,"high":6050.244,"low":6028.598,"close":6047.413},
  {"datetime":"2025-08-18T12:00:00+00:00","date":"2025-08-18","epoch":1755518400,"open":6047.342,"high":6067.633,"low":6046.953,"close":6049.849},
  {"datetime":"2025-08-18T16:00:00+00:00","date":"2025-08-18","epoch":1755532800,"open":6049.784,"high":6059.684,"low":6042.907,"close":6052.016},
  {"datetime":"2025-08-18T20:00:00+00:00","date":"2025-08-18","epoch":1755547200,"open":6051.942,"high":6056.099,"low":6039.369,"close":6048.935},
  {"datetime":"2025-08-19T00:00:00+00:00","date":"2025-08-19","epoch":1755561600,"open":6048.811,"high":6059.372,"low":6040.302,"close":6058.235},
  {"datetime":"2025-08-19T04:00:00+00:00","date":"2025-08-19","epoch":1755576000,"open":6058.164,"high":6074.749,"low":6053.329,"close":6063.906},
  {"datetime":"2025-08-19T08:00:00+00:00","date":"2025-08-19","epoch":1755590400,"open":6064.122,"high":6072.635,"low":6052.888,"close":6068.395},
  {"datetime":"2025-08-19T12:00:00+00:00","date":"2025-08-19","epoch":1755604800,"open":6068.409,"high":6071.777,"low":6043.519,"close":6047.936},
  {"datetime":"2025-08-19T16:00:00+00:00","date":"2025-08-19","epoch":1755619200,"open":6047.862,"high":6058.577,"low":6041.93,"close":6044.386},
  {"datetime":"2025-08-19T20:00:00+00:00","date":"2025-08-19","epoch":1755633600,"open":6044.415,"high":6056.519,"low":6038.713,"close":6042.15},
  {"datetime":"2025-08-20T00:00:00+00:00","date":"2025-08-20","epoch":1755648000,"open":6042.102,"high":6055.041,"low":6034.703,"close":6050.388},
  {"datetime":"2025-08-20T04:00:00+00:00","date":"2025-08-20","epoch":1755662400,"open":6050.209,"high":6054.012,"low":6042.176,"close":6047.426},
  {"datetime":"2025-08-20T08:00:00+00:00","date":"2025-08-20","epoch":1755676800,"open":6047.206,"high":6048.019,"low":6030.999,"close":6037.999},
  {"datetime":"2025-08-20T12:00:00+00:00","date":"2025-08-20","epoch":1755691200,"open":6038.002,"high":6041.36,"low":6015.033,"close":6040.319},
  {"datetime":"2025-08-20T16:00:00+00:00","date":"2025-08-20","epoch":1755705600,"open":6040.305,"high":6054.34,"low":6034.179,"close":6039.153},
  {"datetime":"2025-08-20T20:00:00+00:00","date":"2025-08-20","epoch":1755720000,"open":6039.073,"high":6054.905,"low":6031.581,"close":6053.714},
  {"datetime":"2025-08-21T00:00:00+00:00","date":"2025-08-21","epoch":1755734400,"open":6053.493,"high":6057.3,"low":6037.082,"close":6039.762},
  {"datetime":"2025-08-21T04:00:00+00:00","date":"2025-08-21","epoch":1755748800,"open":6039.38,"high":6039.38,"low":6017.452,"close":6028.421},
  {"datetime":"2025-08-21T08:00:00+00:00","date":"2025-08-21","epoch":1755763200,"open":6028.546,"high":6038.489,"low":6021.68,"close":6025.547},
  {"datetime":"2025-08-21T12:00:00+00:00","date":"2025-08-21","epoch":1755777600,"open":6025.68,"high":6029.098,"low":6010.853,"close":6011.227},
  {"datetime":"2025-08-21T16:00:00+00:00","date":"2025-08-21","epoch":1755792000,"open":6011.377,"high":6019.066,"low":6004.316,"close":6005.259},
  {"datetime":"2025-08-21T20:00:00+00:00","date":"2025-08-21","epoch":1755806400,"open":6005.305,"high":6007.631,"low":5982.423,"close":5990.637},
  {"datetime":"2025-08-22T00:00:00+00:00","date":"2025-08-22","epoch":1755820800,"open":5990.688,"high":6010.979,"low":5987.456,"close":6007.214},
  {"datetime":"2025-08-22T04:00:00+00:00","date":"2025-08-22","epoch":1755835200,"open":6007.082,"high":6014.965,"low":5990.687,"close":5999.136},
  {"datetime":"2025-08-22T08:00:00+00:00","date":"2025-08-22","epoch":1755849600,"open":5999.099,"high":6001.909,"low":5988.626,"close":6000.37},
  {"datetime":"2025-08-22T12:00:00+00:00","date":"2025-08-22","epoch":1755864000,"open":6000.176,"high":6012.703,"low":5990.736,"close":6008.601},
  {"datetime":"2025-08-22T16:00:00+00:00","date":"2025-08-22","epoch":1755878400,"open":6008.596,"high":6014.671,"low":5999.76,"close":6004.441},
  {"datetime":"2025-08-22T20:00:00+00:00","date":"2025-08-22","epoch":1755892800,"open":6004.421,"high":6013.087,"low":5984.886,"close":5985.023},
  {"datetime":"2025-08-23T00:00:00+00:00","date":"2025-08-23","epoch":1755907200,"open":5984.883,"high":6012.602,"low":5984.768,"close":6004.311},
  {"datetime":"2025-08-23T04:00:00+00:00","date":"2025-08-23","epoch":1755921600,"open":6004.432,"high":6022.638,"low":6004.293,"close":6007.19},
  {"datetime":"2025-08-23T08:00:00+00:00","date":"2025-08-23","epoch":1755936000,"open":6007.121,"high":6024.51,"low":5997.832,"close":6021.921},
  {"datetime":"2025-08-23T12:00:00+00:00","date":"2025-08-23","epoch":1755950400,"open":6021.977,"high":6034.77,"low":6019.292,"close":6027.901},
  {"datetime":"2025-08-23T16:00:00+00:00","date":"2025-08-23","epoch":1755964800,"open":6027.808,"high":6042.05,"low":6023.196,"close":6035.77},
  {"datetime":"2025-08-23T20:00:00+00:00","date":"2025-08-23","epoch":1755979200,"open":6035.664,"high":6039.769,"low":6023.636,"close":6030.876},
  {"datetime":"2025-08-24T00:00:00+00:00","date":"2025-08-24","epoch":1755993600,"open":6031.025,"high":6050.082,"low":6028.272,"close":6040.492},
  {"datetime":"2025-08-24T04:00:00+00:00","date":"2025-08-24","epoch":1756008000,"open":6040.282,"high":6050.664,"low":6030.373,"close":6046.668},
  {"datetime":"2025-08-24T08:00:00+00:00","date":"2025-08-24","epoch":1756022400,"open":6046.575,"high":6060.535,"low":6045.692,"close":6048.827},
  {"datetime":"2025-08-24T12:00:00+00:00","date":"2025-08-24","epoch":1756036800,"open":6048.703,"high":6054.184,"low":6035.782,"close":6049.057},
  {"datetime":"2025-08-24T16:00:00+00:00","date":"2025-08-24","epoch":1756051200,"open":6048.949,"high":6059.644,"low":6042.107,"close":6052.387},
  {"datetime":"2025-08-24T20:00:00+00:00","date":"2025-08-24","epoch":1756065600,"open":6052.409,"high":6058.427,"low":6041.849,"close":6051.795},
  {"datetime":"2025-08-25T00:00:00+00:00","date":"2025-08-25","epoch":1756080000,"open":6051.819,"high":6066.316,"low":6048.906,"close":6055.858},
  {"datetime":"2025-08-25T04:00:00+00:00","date":"2025-08-25","epoch":1756094400,"open":6056.211,"high":6058.975,"low":6040.914,"close":6049.08},
  {"datetime":"2025-08-25T08:00:00+00:00","date":"2025-08-25","epoch":1756108800,"open":6049.222,"high":6049.711,"low":6023.546,"close":6024.172},
  {"datetime":"2025-08-25T12:00:00+00:00","date":"2025-08-25","epoch":1756123200,"open":6023.861,"high":6027.174,"low":6016.426,"close":6018.762},
  {"datetime":"2025-08-25T16:00:00+00:00","date":"2025-08-25","epoch":1756137600,"open":6018.593,"high":6030.314,"low":6011.38,"close":6019.531},
  {"datetime":"2025-08-25T20:00:00+00:00","date":"2025-08-25","epoch":1756152000,"open":6019.336,"high":6036.637,"low":6009.84,"close":6034.13}
]}

df = pd.DataFrame(data["series"])
df["datetime"] = pd.to_datetime(df["datetime"])
df.set_index("datetime", inplace=True)
df = df[["open","high","low","close","epoch","date"]]
df.reset_index().to_csv("prices.csv", index=False)

# ---- 2) Helpers ----

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    prev_c = c.shift(1)
    tr = pd.concat([(h - l).abs(),
                    (h - prev_c).abs(),
                    (l - prev_c).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()

def compute_fractals(df: pd.DataFrame, k: int = 2,
                     strict_left: bool = True, strict_right: bool = False):
    """
    Confirmed k-bar fractals (no repaint):
    - Swing High at i if:
        (strict_left ? high[i] >  max(high[i-k:i]) : >=) and
        (strict_right ? high[i] > max(high[i+1:i+k+1]) : >=)
    - Swing Low analogous.
    """
    highs = df["high"].to_numpy()
    lows  = df["low"].to_numpy()
    n = len(df)

    if k < 1 or n < 2*k + 1:
        return [], []  # not enough data to have k bars on both sides

    swing_highs, swing_lows = [], []

    for i in range(k, n - k):
        # previous k bars (left window) and next k bars (right window)
        left_h_max  = np.max(highs[i - k:i])
        right_h_max = np.max(highs[i + 1:i + k + 1])

        left_l_min  = np.min(lows[i - k:i])
        right_l_min = np.min(lows[i + 1:i + k + 1])

        # tie policies
        if strict_left:
            cond_left_high = highs[i] > left_h_max
            cond_left_low  = lows[i]  < left_l_min
        else:
            cond_left_high = highs[i] >= left_h_max
            cond_left_low  = lows[i]  <= left_l_min

        if strict_right:
            cond_right_high = highs[i] > right_h_max
            cond_right_low  = lows[i]  < right_l_min
        else:
            cond_right_high = highs[i] >= right_h_max
            cond_right_low  = lows[i]  <= right_l_min

        if cond_left_high and cond_right_high:
            swing_highs.append((i, df.index[i], float(highs[i])))
        if cond_left_low and cond_right_low:
            swing_lows.append((i, df.index[i], float(lows[i])))

    return swing_highs, swing_lows


def label_structure(pivots: List[Tuple[int, pd.Timestamp, float]], kind: str):
    # kind: "high" or "low"
    labels = []
    prev_price = None
    for i, ts, price in pivots:
        if prev_price is None:
            labels.append("N/A")
        else:
            if kind == "high":
                labels.append("HH" if price > prev_price else "LH")
            else:  # low
                labels.append("HL" if price > prev_price else "LL")
        prev_price = price
    return labels

def compute_bos_choch(df: pd.DataFrame, swing_highs, swing_lows):
    """
    Detect BOS (break of structure) and CHOCH (change of character) events
    using *close-price breaches* of the most recent confirmed swing high/low.

    Parameters
    ----------
    df : DataFrame with a DatetimeIndex and a 'close' column.
    swing_highs : list of tuples [(i, ts, price), ...] from compute_fractals or zigzag
    swing_lows  : list of tuples [(i, ts, price), ...] from compute_fractals or zigzag

    Returns
    -------
    events_df : DataFrame with columns:
        ['event_id','event_type','breach_ts','breach_price',
         'breached_pivot_type','breached_pivot_index','breached_pivot_ts','breached_pivot_price',
         'mode']
    """
    closes = df["close"].values
    times = df.index

    sh_map = {i: (ts, price) for (i, ts, price) in swing_highs}
    sl_map = {i: (ts, price) for (i, ts, price) in swing_lows}
    sh_indices = sorted(sh_map.keys())
    sl_indices = sorted(sl_map.keys())

    events = []
    event_id = 1
    last_bos_dir = 0  # +1 for up BOS, -1 for down BOS

    last_sh_idx = None
    last_sl_idx = None
    sh_already_breached = set()
    sl_already_breached = set()

    for i in range(len(df)):
        # update the "most recent" confirmed pivots as we pass their indices
        # (pivots are confirmed historically; we just need latest one <= i)
        while sh_indices and sh_indices[0] <= i:
            last_sh_idx = sh_indices.pop(0)
        while sl_indices and sl_indices[0] <= i:
            last_sl_idx = sl_indices.pop(0)

        # Up BOS: close breaks above last swing high price (and we haven't recorded it yet)
        if last_sh_idx is not None and last_sh_idx not in sh_already_breached:
            sh_ts, sh_price = sh_map[last_sh_idx]
            if closes[i] > sh_price:
                events.append({
                    "event_id": event_id,
                    "event_type": "BOS_UP",
                    "breach_ts": times[i],
                    "breach_price": closes[i],
                    "breached_pivot_type": "SH",
                    "breached_pivot_index": last_sh_idx,
                    "breached_pivot_ts": sh_ts,
                    "breached_pivot_price": sh_price,
                    "mode": "close"
                })
                event_id += 1
                # CHOCH if previous BOS was down
                if last_bos_dir == -1:
                    events.append({
                        "event_id": event_id,
                        "event_type": "CHOCH_UP",
                        "breach_ts": times[i],
                        "breach_price": closes[i],
                        "breached_pivot_type": "SH",
                        "breached_pivot_index": last_sh_idx,
                        "breached_pivot_ts": sh_ts,
                        "breached_pivot_price": sh_price,
                        "mode": "close"
                    })
                    event_id += 1
                last_bos_dir = +1
                sh_already_breached.add(last_sh_idx)

        # Down BOS: close breaks below last swing low price (and we haven't recorded it yet)
        if last_sl_idx is not None and last_sl_idx not in sl_already_breached:
            sl_ts, sl_price = sl_map[last_sl_idx]
            if closes[i] < sl_price:
                events.append({
                    "event_id": event_id,
                    "event_type": "BOS_DOWN",
                    "breach_ts": times[i],
                    "breach_price": closes[i],
                    "breached_pivot_type": "SL",
                    "breached_pivot_index": last_sl_idx,
                    "breached_pivot_ts": sl_ts,
                    "breached_pivot_price": sl_price,
                    "mode": "close"
                })
                event_id += 1
                # CHOCH if previous BOS was up
                if last_bos_dir == +1:
                    events.append({
                        "event_id": event_id,
                        "event_type": "CHOCH_DOWN",
                        "breach_ts": times[i],
                        "breach_price": closes[i],
                        "breached_pivot_type": "SL",
                        "breached_pivot_index": last_sl_idx,
                        "breached_pivot_ts": sl_ts,
                        "breached_pivot_price": sl_price,
                        "mode": "close"
                    })
                    event_id += 1
                last_bos_dir = -1
                sl_already_breached.add(last_sl_idx)

    return pd.DataFrame(events)


# ---- ZigZag with dynamic threshold (max(pct * price, atr_mult * ATR14)) ----

def compute_zigzag(df: pd.DataFrame,
                   pct_threshold: float = 0.015,
                   atr_mult: float = 2.0,
                   atr_series: pd.Series | None = None):
    """
    Non-repainting ZigZag: lock a pivot at the *run extreme* when a reversal
    from that extreme >= threshold is observed. Confirmation bar = first bar
    where reversal condition is satisfied.

    Returns
    -------
    pivots : list of dicts:
        {'type': 'SH'|'SL', 'i': idx, 'ts': Timestamp, 'price': float,
         'confirmed_at': Timestamp, 'threshold': float, 'basis': 'max'}
    """
    if atr_series is None:
        atr_series = atr(df, 14)
    atr_vals = atr_series.values

    highs = df["high"].values
    lows = df["low"].values
    times = df.index
    n = len(df)
    if n == 0:
        return []

    pivots = []
    # Start state
    dir_ = 0            # 0 unknown, +1 up-run, -1 down-run
    pivot_i = 0
    pivot_price = df["close"].iloc[0]
    run_high = highs[0]; run_high_i = 0
    run_low  = lows[0];  run_low_i  = 0

    for i in range(1, n):
        # update run extremes
        if highs[i] > run_high:
            run_high = highs[i]
            run_high_i = i
        if lows[i] < run_low:
            run_low = lows[i]
            run_low_i = i

        # helper to compute current absolute threshold from a reference price
        def abs_threshold(ref_price: float) -> float:
            return max(pct_threshold * ref_price, atr_mult * atr_vals[i])

        if dir_ == 0:
            # establish initial direction once move from the starting pivot exceeds threshold
            if (run_high - pivot_price) >= abs_threshold(pivot_price):
                dir_ = +1
            elif (pivot_price - run_low) >= abs_threshold(pivot_price):
                dir_ = -1
            continue

        if dir_ == +1:
            # reversal from *high extreme* down to current low
            thr = abs_threshold(run_high)
            if (run_high - lows[i]) >= thr:
                # lock swing high at the high extreme bar
                pivots.append({
                    "type": "SH",
                    "i": run_high_i,
                    "ts": times[run_high_i],
                    "price": run_high,
                    "confirmed_at": times[i],
                    "threshold": thr,
                    "basis": "max"
                })
                # new pivot becomes that SH; switch to down-run
                pivot_i = run_high_i
                pivot_price = run_high
                dir_ = -1
                # reset extremes starting from current bar
                run_low = lows[i]; run_low_i = i
                run_high = highs[i]; run_high_i = i

        else:  # dir_ == -1
            # reversal from *low extreme* up to current high
            thr = abs_threshold(run_low)
            if (highs[i] - run_low) >= thr:
                # lock swing low at the low extreme bar
                pivots.append({
                    "type": "SL",
                    "i": run_low_i,
                    "ts": times[run_low_i],
                    "price": run_low,
                    "confirmed_at": times[i],
                    "threshold": thr,
                    "basis": "max"
                })
                # new pivot becomes that SL; switch to up-run
                pivot_i = run_low_i
                pivot_price = run_low
                dir_ = +1
                # reset extremes starting from current bar
                run_low = lows[i]; run_low_i = i
                run_high = highs[i]; run_high_i = i

    # (Optional) do not force-lock the final incomplete extremum; most implementations leave it floating
    return pivots


# ---- Build outputs for both methods & save ----
import json

# ATR series (used by ZigZag and for reporting)
df["ATR14"] = atr(df, 14)

# Fractal pivots
swing_highs, swing_lows = compute_fractals(df, k=4)
fr_high_labels = label_structure(swing_highs, "high")
fr_low_labels  = label_structure(swing_lows, "low")

fractal_rows = []
for (row, (i, ts, price)) in enumerate(swing_highs):
    fractal_rows.append({
        "algo": "fractal",
        "pivot_id": f"FR_SH_{i}",
        "type": "SH",
        "index": i,
        "ts": ts,
        "price": price,
        "label": fr_high_labels[row],
        "confirmed_at": ts,   # confirmation is k bars ahead in logic, but we stamp the pivot bar for simplicity
        "lookahead": 2
    })
for (row, (i, ts, price)) in enumerate(swing_lows):
    fractal_rows.append({
        "algo": "fractal",
        "pivot_id": f"FR_SL_{i}",
        "type": "SL",
        "index": i,
        "ts": ts,
        "price": price,
        "label": fr_low_labels[row],
        "confirmed_at": ts,
        "lookahead": 2
    })

fractal_pivots_df = pd.DataFrame(fractal_rows).sort_values(["index", "type"]).reset_index(drop=True)
fractal_events_df = compute_bos_choch(df, swing_highs, swing_lows)
if not fractal_events_df.empty:
    fractal_events_df.insert(0, "algo", "fractal")

# ZigZag pivots
zz_pivots = compute_zigzag(df, pct_threshold=0.008, atr_mult=1.0, atr_series=df["ATR14"])

# Split to SH/SL for labeling and BOS/CHOCH
zz_highs = [(p["i"], p["ts"], p["price"]) for p in zz_pivots if p["type"] == "SH"]
zz_lows  = [(p["i"], p["ts"], p["price"]) for p in zz_pivots if p["type"] == "SL"]

zz_high_labels = label_structure(zz_highs, "high")
zz_low_labels  = label_structure(zz_lows,  "low")

zigzag_rows = []
for (row, (i, ts, price)) in enumerate(zz_highs):
    # find the original pivot dict to pull confirmation and threshold
    meta = next(p for p in zz_pivots if p["type"] == "SH" and p["i"] == i)
    zigzag_rows.append({
        "algo": "zigzag",
        "pivot_id": f"ZZ_SH_{i}",
        "type": "SH",
        "index": i,
        "ts": ts,
        "price": price,
        "label": zz_high_labels[row],
        "confirmed_at": meta["confirmed_at"],
        "threshold_used": meta["threshold"],
        "threshold_basis": meta["basis"]
    })
for (row, (i, ts, price)) in enumerate(zz_lows):
    meta = next(p for p in zz_pivots if p["type"] == "SL" and p["i"] == i)
    zigzag_rows.append({
        "algo": "zigzag",
        "pivot_id": f"ZZ_SL_{i}",
        "type": "SL",
        "index": i,
        "ts": ts,
        "price": price,
        "label": zz_low_labels[row],
        "confirmed_at": meta["confirmed_at"],
        "threshold_used": meta["threshold"],
        "threshold_basis": meta["basis"]
    })

zigzag_pivots_df = pd.DataFrame(zigzag_rows).sort_values(["index", "type"]).reset_index(drop=True)

# ZigZag legs
zigzag_legs = []
zz_sorted = sorted(zz_pivots, key=lambda p: p["i"])
for leg_id, (p_start, p_end) in enumerate(zip(zz_sorted, zz_sorted[1:]), start=1):
    direction = "down" if p_start["type"] == "SH" else "up"
    start_i, end_i = p_start["i"], p_end["i"]
    start_price, end_price = p_start["price"], p_end["price"]
    abs_move = end_price - start_price
    pct_move = (abs_move / start_price) * 100.0 if start_price != 0 else np.nan
    atr_at_start = float(df["ATR14"].iloc[start_i]) if not pd.isna(df["ATR14"].iloc[start_i]) else np.nan
    atr_move = abs(abs_move) / atr_at_start if atr_at_start and not np.isnan(atr_at_start) else np.nan

    zigzag_legs.append({
        "algo": "zigzag",
        "leg_id": leg_id,
        "direction": direction,
        "start_index": start_i,
        "start_ts": df.index[start_i],
        "start_price": start_price,
        "end_index": end_i,
        "end_ts": df.index[end_i],
        "end_price": end_price,
        "abs_move": abs_move,
        "pct_move": pct_move,
        "atr_move": atr_move,
        "bars": end_i - start_i
    })
zigzag_legs_df = pd.DataFrame(zigzag_legs)

# ZigZag BOS/CHOCH
zigzag_events_df = compute_bos_choch(df, zz_highs, zz_lows)
if not zigzag_events_df.empty:
    zigzag_events_df.insert(0, "algo", "zigzag")

# Save outputs
fractal_pivots_df.to_csv("fractal_pivots.csv", index=False)
zigzag_pivots_df.to_csv("zigzag_pivots.csv", index=False)
zigzag_legs_df.to_csv("zigzag_legs.csv", index=False)

events_df = pd.concat([fractal_events_df, zigzag_events_df], ignore_index=True) if (
    (fractal_events_df is not None and not fractal_events_df.empty) or
    (zigzag_events_df is not None and not zigzag_events_df.empty)
) else pd.DataFrame(columns=[
    "algo","event_id","event_type","breach_ts","breach_price",
    "breached_pivot_type","breached_pivot_index","breached_pivot_ts","breached_pivot_price","mode"
])
events_df.to_csv("events.csv", index=False)

summary = {
    "meta": {
        "records": int(len(df)),
        "atr_period": 14,
        "fractal_k": 2,
        "zigzag": {"pct_threshold": 0.015, "atr_mult": 2.0, "breach_mode": "close"}
    },
    "counts": {
        "fractal": {
            "pivots": int(len(fractal_pivots_df)),
            "events": int(len(fractal_events_df)) if fractal_events_df is not None else 0
        },
        "zigzag": {
            "pivots": int(len(zigzag_pivots_df)),
            "legs": int(len(zigzag_legs_df)),
            "events": int(len(zigzag_events_df)) if zigzag_events_df is not None else 0
        }
    }
}
with open("summary.json", "w") as f:
    json.dump(summary, f, default=str, indent=2)

print("Saved: fractal_pivots.csv, zigzag_pivots.csv, zigzag_legs.csv, events.csv, summary.json")

