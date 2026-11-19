// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

/// @notice TechNeighbor hackathon demonstration fund. Deploy only on Arc Testnet.
/// @dev Random receipt IDs never encode a resident, booking, topic or contact detail.
contract CommunityFund {
    address public owner;
    address public operator;
    uint256 public constant REWARD = 2 ether; // Arc native test USDC uses 18 decimals.
    uint256 public constant DAILY_LIMIT = 10;
    uint256 public totalFunded;
    uint256 public totalRewarded;
    uint256 public rewardCount;
    mapping(uint256 => uint256) public rewardsPerDay;
    struct Reward { address recipient; uint256 amount; uint256 paidAt; }
    mapping(bytes32 => Reward) public rewards;

    event Funded(address indexed sponsor, uint256 amount);
    event RewardPaid(bytes32 indexed id, address indexed recipient, uint256 amount);

    constructor(address approvedOperator) {
        require(approvedOperator != address(0), "Invalid operator");
        owner = msg.sender;
        operator = approvedOperator;
    }

    receive() external payable {
        require(msg.value > 0, "Empty contribution");
        totalFunded += msg.value;
        emit Funded(msg.sender, msg.value);
    }

    function payReward(bytes32 id, address payable recipient) external {
        require(msg.sender == operator, "Operator only");
        require(id != bytes32(0) && rewards[id].paidAt == 0, "Receipt already used");
        require(recipient != address(0) && recipient != address(this), "Invalid recipient");
        require(rewardsPerDay[block.timestamp / 1 days] < DAILY_LIMIT, "Daily limit reached");
        require(address(this).balance >= REWARD, "Fund needs test USDC");
        rewards[id] = Reward(recipient, REWARD, block.timestamp);
        rewardsPerDay[block.timestamp / 1 days] += 1;
        totalRewarded += REWARD;
        rewardCount += 1;
        (bool success,) = recipient.call{value: REWARD}("");
        require(success, "Reward transfer failed");
        emit RewardPaid(id, recipient, REWARD);
    }
}
