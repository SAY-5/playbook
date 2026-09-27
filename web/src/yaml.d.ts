/* A .yaml import is parsed at build time by the plugin in vite.config.ts; loadRubric and
   loadScenarios in sim/scenarios.ts validate the shape. */
declare module "*.yaml" {
  const data: unknown;
  export default data;
}
