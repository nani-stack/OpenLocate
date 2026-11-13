// A fixed demo route of about 1 km along the Reflecting Pool on the National Mall,
// Washington DC, from the Lincoln Memorial end towards the Washington Monument.

import type { RoutePoint } from "./rpc/types";

export const DEMO_ROUTE_NAME = "National Mall, Washington DC (about 1 km)";

export const DEMO_ROUTE: readonly RoutePoint[] = [
  [38.88935, -77.04815],
  [38.88942, -77.04690],
  [38.88946, -77.04560],
  [38.88947, -77.04430],
  [38.88946, -77.04300],
  [38.88945, -77.04170],
  [38.88944, -77.04040],
  [38.88942, -77.03910],
  [38.88938, -77.03780],
  [38.88934, -77.03660],
];
