const Ajv = require("ajv/dist/2020");
const addFormats = require("ajv-formats");
const fs = require("fs");
const path = require("path");

const ajv = new Ajv({ allErrors: true });
addFormats(ajv);

function loadSchema(name) {
  const filePath = path.join(__dirname, name);
  return JSON.parse(fs.readFileSync(filePath, "utf-8"));
}

const analysisSchema = loadSchema("analysis.schema.json");
const itemsSchema = loadSchema("items.schema.json");

const validateAnalysisSchema = ajv.compile(analysisSchema);
const validateItemsSchema = ajv.compile(itemsSchema);

/**
 * Validate analysis data against analysis.schema.json.
 * @param {object} data
 * @returns {string[]} Array of error messages (empty = valid)
 */
function validateAnalysis(data) {
  const valid = validateAnalysisSchema(data);
  if (valid) return [];
  return validateAnalysisSchema.errors.map(
    (e) => `${e.instancePath || "/"}: ${e.message}`
  );
}

/**
 * Validate scored items against items.schema.json.
 * @param {Array} data
 * @returns {string[]} Array of error messages (empty = valid)
 */
function validateItems(data) {
  const valid = validateItemsSchema(data);
  if (valid) return [];
  return validateItemsSchema.errors.map(
    (e) => `${e.instancePath || "/"}: ${e.message}`
  );
}

module.exports = { validateAnalysis, validateItems };
