// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

/// @notice One organization's service statements; no resident or session data.
/// @dev This proves the issuer's statement, not service quality or volunteer safety.
contract ServiceCredentials {
    address public issuer;
    struct Credential { address volunteer; uint64 issuedAt; uint64 revokedAt; }
    mapping(bytes32 => Credential) public credentials;
    event Issued(bytes32 indexed id, address indexed volunteer);
    event Revoked(bytes32 indexed id);

    constructor() { issuer = msg.sender; }
    modifier onlyIssuer() { require(msg.sender == issuer, "Issuer only"); _; }

    function issue(bytes32 id, address volunteer) external onlyIssuer {
        require(id != bytes32(0), "Empty ID");
        require(volunteer != address(0), "Empty volunteer");
        require(credentials[id].issuedAt == 0, "Already issued");
        credentials[id] = Credential(volunteer, uint64(block.timestamp), 0);
        emit Issued(id, volunteer);
    }

    function revoke(bytes32 id) external onlyIssuer {
        Credential storage credential = credentials[id];
        require(credential.issuedAt != 0, "Unknown credential");
        require(credential.revokedAt == 0, "Already revoked");
        credential.revokedAt = uint64(block.timestamp);
        emit Revoked(id);
    }
}
