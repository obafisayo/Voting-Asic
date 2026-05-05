`timescale 1ns/1ps

module tb_voting_system();
    // Signal Declarations
    reg clk, rst_n;
    reg [7:0] ui_in_val;
    reg [7:0] uio_in_val;
    wire [7:0] uo_out;

    // Helper wire to monitor the FSM state directly
    wire [2:0] status = uo_out[2:0];

    // Instantiate the Top-Level ASIC Module
    tt_um_voting_asic uut (
        .ui_in(ui_in_val),
        .uo_out(uo_out),
        .uio_in(uio_in_val),
        .uio_out(),
        .uio_oe(),
        .ena(1'b1),
        .clk(clk),
        .rst_n(rst_n)
    );

    // Clock Generation: 100MHz (10ns period)
    always #5 clk = ~clk;

    initial begin
        // 1. Termux Output Setup
        // $monitor ensures every signal change is printed immediately
        $monitor("TIME: %0t | STATE: %b | ID_VALID: %b | DUP: %b", $time, status, uo_out[3], uo_out[4]);
        
        $display("--- STARTING VALID VOTE TEST ---");
        clk = 0; rst_n = 0; ui_in_val = 0; uio_in_val = 0;
        
        // 2. Hardware Reset
        #100 rst_n = 1;
        $strobe("[%0t] Reset released. System in IDLE.", $time);
        
        // 3. Load Valid Voter ID: 0xA0001
        // Step A: Load Lower Byte (0x01)
        #20 ui_in_val = 8'h01; 
            uio_in_val = 8'b0000_0101; // byte_write=1, byte_sel=2'b01
        #20 uio_in_val = 8'b0;         // Clear control signals

        // Step B: Load Upper Byte (0x00) + Upper Nibble (0xA)
        #20 ui_in_val = 8'h00; 
            uio_in_val = 8'b1010_0110; // nibble=4'hA, byte_write=1, byte_sel=2'b10
        #20 uio_in_val = 8'b0;         // Clear control signals

        // 4. Trigger the FSM
        #20 ui_in_val = 8'b0000_0010;  // Select Candidate #2
            uio_in_val = 8'b0000_1000; // Assert data_ready=1
        #20 uio_in_val = 8'b0000_0000; // De-assert data_ready (Clear Handshake)

        // 5. Success/Failure Detection
        // We use a fork-join to wait for the VOTE_CAST state (011) or time out
        fork
            begin
                // Wait specifically for the success state
                wait(status == 3'b011); 
                $display("\n[SUCCESS] Time: %0t | FSM reached VOTE_CAST state!", $time);
                #40 $display("--- TEST COMPLETE: SUCCESS ---");
                $finish;
            end
            begin
                // Safety timeout: stop if success isn't reached in 2 microseconds
                #2000; 
                $display("\n[FAILURE] Time: %0t | Test timed out. FSM stuck at state %b", $time, status);
                $finish;
            end
        join
    end

endmodule