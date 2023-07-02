import random
import time
import json
from web3 import Web3
from web3.providers.rpc import HTTPProvider
from termcolor import colored
from loguru import logger


'''
    Bridge MIM on Abracadabra 
    chains : Moonriver | Fantom 
'''

from_chain_name = "Moonriver"    # Origin chain for transfer.
to_chain_name = "Fantom"         # Destination chain for transfer.
min_amount = 0.01                # Minimum token transfer amount.
max_amount = 0.04                # Maximum token transfer amount.
delay_range = (30, 60)           # Pause duration after each transfer, in seconds.
random_wallets = True            # If True, wallets are processed in random order.
max_attempts = 2                 # Maximum attempts to execute a transfer for each wallet.
bridge_all_balance = True        # If True, entire wallet balance is transferred.
            

with open('bridge_abi.json') as f:
    bridge_abi = json.load(f)
with open('mim_abi.json') as f:
    mim_abi = json.load(f)

class Chain():
    def __init__(self, rpc_url, bridge_address, mim_address, chainId, blockExplorerUrl):
        self.w3 = Web3(HTTPProvider(rpc_url))
        self.bridge_address = self.w3.to_checksum_address(bridge_address)
        self.bridge_contract = self.w3.eth.contract(
            address=self.bridge_address, abi=bridge_abi)
        self.mim_address = self.w3.to_checksum_address(mim_address)
        self.mim_contract = self.w3.eth.contract(
            address=self.mim_address, abi=mim_abi)
        self.chain_id = chainId
        self.blockExplorerUrl = blockExplorerUrl


class Fantom(Chain):
    def __init__(self):
        super().__init__(
            'https://rpc.ankr.com/fantom',  # rpc
            '0xc5c01568a3b5d8c203964049615401aaf0783191',  # bridge contract
            '0x82f0B8B456c1A451378467398982d4834b6829c1',  # MIM contract
            112,  # Chain ID LZ
            'https://ftmscan.com'  # explorer
        )


class Moonriver(Chain):
    def __init__(self):
        super().__init__(
            'https://rpc.api.moonriver.moonbeam.network',  # rpc
            '0xef2dbdfec54c466f7ff92c9c5c75abb6794f0195',  # bridge contract
            '0x0caE51e1032e8461f4806e26332c030E34De3aDb',  # MIM contract
            167,  # Chain ID LZ
            'https://moonriver.moonscan.io/'  # explorer
        )


class ChainSelector:
    def __init__(self):
        self.chains = {
            "Fantom": Fantom(),
            "Moonriver": Moonriver()
        }

    def get_chain(self, chain_name):
        return self.chains.get(chain_name)

    def select_chains(self, from_chain_name, to_chain_name):
        from_chain = self.get_chain(from_chain_name)
        to_chain = self.get_chain(to_chain_name)

        if from_chain is None or to_chain is None:
            raise ValueError(
                "Wrong network name")

        return from_chain, to_chain


def bridge_mim(chain_from, chain_to, private_key, max_attempts, bridge_all_balance):
    try:
        account = chain_from.w3.eth.account.from_key(private_key)
        address_bytes = bytes.fromhex(account.address[2:])
        address_bytes_32 = bytes(12) + address_bytes

        tx_data = (
            "0x000200000000000000000000000000000000000000000000000000000000000186a"
            "00000000000000000000000000000000000000000000000000000000000000000"
            f"{account.address[2:]}"
        )

        if bridge_all_balance:
            amount = check_balance(account.address, chain_from.mim_contract)
        else:
            amount = random.randint(int(min_amount*10**18), int(max_amount*10**18))

        for attempt in range(1, max_attempts+1):
            try:
                nonce = chain_from.w3.eth.get_transaction_count(
                    account.address)
                gas_price = chain_from.w3.eth.gas_price

                fees = chain_from.bridge_contract.functions.estimateSendFee(
                    chain_to.chain_id,
                    address_bytes_32,
                    amount,
                    True,
                    tx_data
                ).call()

                fee = fees[0]

                bridge_txn = chain_from.bridge_contract.functions.sendFrom(
                    account.address, chain_to.chain_id, address_bytes_32, amount, (
                        account.address, "0x0000000000000000000000000000000000000000", tx_data)
                ).build_transaction({
                    'from': account.address,
                    'value': fee,
                    'gasPrice': gas_price,
                    'nonce': nonce,
                })

                gasLimit = chain_from.w3.eth.estimate_gas(bridge_txn)
                bridge_txn['gas'] = int(gasLimit * random.uniform(1.05, 1.1))

                signed_bridge_txn = chain_from.w3.eth.account.sign_transaction(
                    bridge_txn, private_key)
                raw_bridge_txn_hash = chain_from.w3.eth.send_raw_transaction(
                    signed_bridge_txn.rawTransaction)
                bridge_txn_hash = chain_from.w3.to_hex(raw_bridge_txn_hash)
                receipt = chain_from.w3.eth.wait_for_transaction_receipt(
                    bridge_txn_hash)

                if receipt['status'] == 1:
                    token_amount = amount / 10**18
                    logger.success(
                        f"{chain_from.__class__.__name__} | Bridge tx sent | Token Amount: {token_amount} | Tx: {chain_from.blockExplorerUrl}/tx/{bridge_txn_hash}")
                    return

            except Exception as e:
                logger.error(f"Error occurred during transaction: {str(e)}")

            logger.warning(f"Attempt {attempt} failed. Retrying...")
            time.sleep(random.randint(5, 10))

        logger.error(
            f"Reached maximum number of attempts. Failed to send bridge tx.")

    except Exception as e:
        logger.error(f"Error occurred during transaction: {str(e)}")


def check_balance(address, contract):
    balance = contract.functions.balanceOf(address).call()
    return balance


def work(private_key, from_chain, to_chain, max_attempts):
    account = from_chain.w3.eth.account.from_key(private_key)
    address = account.address
    chains = [(from_chain, to_chain, bridge_mim)]

    for (from_chain, to_chain, bridge_fn) in chains:
        try:
            bridge_fn(from_chain, to_chain, private_key, max_attempts, bridge_all_balance)
        except Exception as e:
            logger.error(f"Error occurred during transaction: {str(e)}")

    logger.info(f'Wallet: {address} | done')

    delay = random.randint(*delay_range)
    logger.info(f"Waiting for {delay} seconds before the next wallet...")
    for i in range(1, delay + 1):
        time.sleep(1)
        print(f"\rsleep : {i}/{delay}", end="")
    print()
    print()
    print()


def main():
    with open('private_keys.txt', 'r') as f:
        private_keys = [row.strip() for row in f]

    total_wallets = len(private_keys)

    chain_selector = ChainSelector()
    from_chain, to_chain = chain_selector.select_chains(
        from_chain_name, to_chain_name)

    if random_wallets:
        random.shuffle(private_keys)

    for wallet_index, private_key in enumerate(private_keys, start=1):
        account = from_chain.w3.eth.account.from_key(private_key)
        address = account.address

        print(f"{wallet_index}/{total_wallets} : {address}")
        print()
        tx_str = f'Abracadabra_bridge : {from_chain_name} => {to_chain_name}'
        logger.info(tx_str)
        logger.info("Starting bridge...")

        work(private_key, from_chain, to_chain, max_attempts)

    logger.info(colored(f'All done', 'green'))


if __name__ == '__main__':
    main()
