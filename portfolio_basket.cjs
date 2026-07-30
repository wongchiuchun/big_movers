const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const filename = path.join(__dirname, 'portfolio_basket.js');
const moduleShim = { exports: {} };
const load = vm.compileFunction(
  fs.readFileSync(filename, 'utf8'),
  ['module', 'exports'],
  { filename }
);
load(moduleShim, moduleShim.exports);

module.exports = moduleShim.exports;
