// Run with Node.js after `npm install --no-save solc@0.8.30`.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const solc = require('solc');
const source = fs.readFileSync(path.join(__dirname, 'ServiceCredentials.sol'), 'utf8');
const input = {language: 'Solidity', sources: {'ServiceCredentials.sol': {content: source}}, settings: {
  optimizer: {enabled: true, runs: 200}, evmVersion: 'paris',
  outputSelection: {'*': {'*': ['abi', 'evm.bytecode.object', 'evm.deployedBytecode.object']}}
}};
const output = JSON.parse(solc.compile(JSON.stringify(input)));
for (const error of output.errors || []) {
  if (error.severity === 'error') throw new Error(error.formattedMessage);
}
const compiled = output.contracts['ServiceCredentials.sol'].ServiceCredentials;
fs.writeFileSync(path.join(__dirname, 'ServiceCredentials.json'), JSON.stringify({
  compiler: solc.version(), evmVersion: 'paris', optimizer: {enabled:true, runs:200},
  source_sha256: crypto.createHash('sha256').update(source).digest('hex'),
  abi: compiled.abi, bytecode: '0x' + compiled.evm.bytecode.object,
  deployedBytecode: '0x' + compiled.evm.deployedBytecode.object,
}, null, 2));
console.log('Compiled ServiceCredentials.sol; ABI and bytecode saved.');
